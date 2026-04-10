---
title: "@Transactional이 걸려있는데 롤백이 안 됐다 — JpaTransactionManager + MyBatis 혼용의 함정"
date: 2026-04-09
lastmod: 2026-04-09
draft: true
tags: ["spring", "jpa", "mybatis", "transaction", "java"]
---

## 1. 시작

`@Transactional`을 메서드에 붙이면 트랜잭션이 동작한다. 예외가 발생하면 롤백된다. 이건 Spring을 쓰는 거의 모든 자바 개발자가 당연하게 받아들이는 전제다.

그런데 이 전제가 깨지는 케이스를 봤다. `@Transactional`이 분명히 걸려있고, 예외도 정상적으로 발생했는데, DB의 일부 변경이 롤백되지 않고 그대로 남아있었다. 작업 상태가 PROCESSING으로 멈춰버린 좀비 레코드가 만들어졌다.

원인을 추적해보니 단순한 버그가 아니라, **JPA와 MyBatis를 한 트랜잭션 안에서 같이 쓸 때 발생하는 구조적 함정**이었다. 이 글은 그 함정을 코드 레벨에서 분석하고, 표면 픽스의 한계와 근본적인 해결책에 대해 이야기한다.

## 2. 사례 — 트랜잭션 안에서 일어난 사일런트한 사고

문제가 된 메서드는 대략 이런 구조였다.

```java
@Transactional(transactionManager = "transactionManager")  // JPA용 트랜잭션 매니저
public Result confirmWork(String workId) {
    // 1. MyBatis: 상태를 PROCESSING으로 변경
    mybatisMapper.updateStatusToProcessing(workId);

    // 2. MyBatis: 검증 + 데이터 변환 + 배치 저장 (전부 MyBatis)
    validateData(workId);
    transformAndSave(workId);
    insertHistories(workId);

    // 3. MyBatis: 상태를 CONFIRMED로 변경
    mybatisMapper.updateStatusToConfirmed(workId);

    // 4. JPA: 작업 로그 저장
    jpaWorkLogManager.saveLog(workId, LogType.CONFIRMED);

    return result;
}
```

대부분의 작업은 MyBatis로 처리하고, 마지막에 감사 로그(audit log)만 JPA로 저장하는 구조였다. 한 트랜잭션 안에 MyBatis와 JPA가 섞여있으니 `JpaTransactionManager`를 명시적으로 지정했다.

`JpaTransactionManager`는 같은 DataSource를 사용하는 MyBatis 쿼리도 동일한 트랜잭션으로 묶을 수 있다고 알려져 있다. 적어도 통설은 그랬다. 그래서 이 코드는 안전해 보였다.

그런데 운영 환경에서 이 메서드의 중간 단계(2번)에서 예외가 발생했고, 1번 단계의 PROCESSING 상태 변경이 **롤백되지 않은 채** 그대로 남았다. 후속 작업이 막혔고, 작업이 좀비 상태로 진입했다.

더 이상한 점은 **로컬 개발 환경에서는 재현되지 않았다**는 것이다. 같은 코드, 같은 어노테이션, 같은 트랜잭션 매니저인데 환경에 따라 동작이 달랐다.

## 3. 첫 번째 단서 — 환경 차이

문제가 발생한 환경과 그렇지 않은 환경의 빈 설정을 비교해봤다.

| 환경 | `transactionManagerLive` (MyBatis 쪽) | `transactionManager` (JPA 쪽) |
|---|---|---|
| 로컬 (전체 구동) | `JpaTransactionManager` | `JpaTransactionManager` |
| 운영 (단독 구동) | `DataSourceTransactionManager` | `JpaTransactionManager` |

차이는 `transactionManagerLive`의 타입이었다. 로컬에서는 양쪽이 모두 `JpaTransactionManager`였고, 운영의 단독 구동 환경에서만 `transactionManagerLive`가 `DataSourceTransactionManager`였다.

코드에서는 `@Transactional("transactionManager")`로 JPA 매니저를 명시했으니, `transactionManagerLive`의 타입과는 관계가 없을 것 같다. 그런데 실제로는 이 차이가 결정적이었다. 왜 그럴까?

답을 찾으려면 두 트랜잭션 매니저가 내부적으로 무엇을 하는지 봐야 한다.

## 4. `DataSourceTransactionManager.doBegin()` — 즉시 커넥션 확보

먼저 단순한 쪽부터. `DataSourceTransactionManager`는 트랜잭션을 시작할 때 다음을 수행한다.

```java
// 단순화된 흐름
protected void doBegin(Object transaction, TransactionDefinition definition) {
    Connection newCon = obtainDataSource().getConnection();   // 1. 즉시 커넥션 획득
    txObject.setConnectionHolder(new ConnectionHolder(newCon), true);

    con.setAutoCommit(false);                                  // 2. 자동 커밋 끔
    txObject.getConnectionHolder().setTransactionActive(true);

    // 3. 현재 스레드에 커넥션 바인딩
    TransactionSynchronizationManager.bindResource(
        obtainDataSource(),
        txObject.getConnectionHolder()
    );
}
```

세 가지가 한 번에 일어난다.

1. DataSource에서 커넥션을 **즉시** 가져온다
2. autoCommit을 false로 바꾼다
3. `TransactionSynchronizationManager`라는 이름의 ThreadLocal 저장소에 이 커넥션을 등록한다

세 번째가 핵심이다. 이후 같은 스레드에서 누군가 이 DataSource로부터 커넥션을 요청하면, 이 ThreadLocal에 등록된 커넥션을 재사용한다. MyBatis가 그 "누군가"에 해당한다.

즉, `DataSourceTransactionManager`로 트랜잭션이 시작되면, 그 안에서 실행되는 모든 MyBatis 쿼리는 자동으로 같은 커넥션을 쓰게 되고, 같은 트랜잭션에 묶인다. 직관적이다.

## 5. `JpaTransactionManager.doBegin()` — 조건부 커넥션 바인딩

이제 JPA 쪽을 보자.

```java
// 단순화된 흐름
protected void doBegin(Object transaction, TransactionDefinition definition) {
    EntityManager newEm = createEntityManagerForTransaction();    // 1. EntityManager만 생성
    txObject.setEntityManagerHolder(new EntityManagerHolder(newEm), true);

    if (getDataSource() != null) {                                 // 2. dataSource가 설정되어 있어야
        ConnectionHandle conHandle = getJpaDialect()
            .getJdbcConnection(em, definition.isReadOnly());       // 3. JpaDialect가 커넥션을 노출해야

        if (conHandle != null) {                                   // 4. null이 아니어야
            ConnectionHolder conHolder = new ConnectionHolder(conHandle);
            TransactionSynchronizationManager.bindResource(
                getDataSource(),
                conHolder
            );
        }
    }
}
```

여기서 ThreadLocal 바인딩은 **세 가지 조건이 모두 만족할 때만** 일어난다.

1. `JpaTransactionManager`에 `setDataSource()`로 DataSource가 설정되어 있어야 한다
2. `JpaDialect.getJdbcConnection()`이 호출되어야 한다
3. 이 호출이 **null이 아닌** 커넥션 핸들을 반환해야 한다

문제는 3번이다. Hibernate는 lazy connection 획득 전략을 사용한다. 즉, 트랜잭션이 시작되는 시점에는 EntityManager만 만들어두고, 실제 DB 커넥션은 첫 JPA 쿼리가 실행되는 순간에 잡는다. 따라서 `doBegin()` 시점의 `getJdbcConnection()`은 null을 반환할 수 있다.

이 경우 ThreadLocal에는 **아무것도 등록되지 않은 채** 트랜잭션이 시작된다.

## 6. ThreadLocal이 비어있을 때 MyBatis가 하는 일

MyBatis가 쿼리를 실행할 때 커넥션이 필요해진다. MyBatis는 `DataSourceUtils.getConnection(dataSource)`를 호출하는데, 이 메서드는 다음과 같이 동작한다.

```java
public static Connection getConnection(DataSource dataSource) {
    // 1. ThreadLocal에 바인딩된 커넥션이 있는가?
    ConnectionHolder conHolder = (ConnectionHolder)
        TransactionSynchronizationManager.getResource(dataSource);

    if (conHolder != null && conHolder.getConnection() != null) {
        return conHolder.getConnection();   // 있으면 재사용
    }

    // 2. 없으면 DataSource에서 직접 가져옴
    return dataSource.getConnection();
}
```

ThreadLocal에 등록된 커넥션이 없으면, MyBatis는 그냥 DataSource에서 새 커넥션을 가져온다. 이 커넥션은 트랜잭션 매니저가 관리하지 않는, **별도의 독립된 커넥션**이다.

그리고 HikariCP의 기본 설정은 `autoCommit=true`다. 트랜잭션 관리 밖의 커넥션은 각 쿼리가 실행되는 즉시 커밋된다. 따라서 MyBatis의 UPDATE는 **DB에 즉시 반영**된다.

## 7. 전체 그림

여기까지 정리하면 사고의 전체 흐름이 보인다.

```
1. @Transactional 시작 (JpaTransactionManager.doBegin)
   - EntityManager 생성
   - getJdbcConnection() → null (Hibernate lazy 전략)
   - ThreadLocal에 커넥션 바인딩 안 됨

2. MyBatis: updateStatusToProcessing() 실행
   - DataSourceUtils.getConnection() 호출
   - ThreadLocal 확인 → 비어있음
   - HikariCP에서 직접 새 커넥션 획득 (autoCommit=true)
   - UPDATE가 즉시 커밋됨 → DB에 PROCESSING 상태 반영

3. 비즈니스 로직 중 예외 발생
   - JPA 호출(saveLog)에 도달하지 못함
   - JpaTransactionManager는 끝까지 커넥션을 잡지 않은 상태

4. 트랜잭션 매니저가 롤백 시도
   - 자신이 관리하는 커넥션이 없음
   - 롤백할 대상 자체가 없음
   - MyBatis가 커밋한 변경은 되돌릴 수 없음
```

`@Transactional` 어노테이션은 분명히 걸려있었다. 트랜잭션 매니저도 정상적으로 시작과 롤백을 시도했다. 그런데 그 사이에서 MyBatis가 트랜잭션 컨텍스트와 무관하게 동작했다. 결과적으로 **트랜잭션이 사실상 존재하지 않은 상태**로 메서드가 실행된 것이다.

## 8. 정상 케이스에서는 왜 발견되지 않는가

이 함정은 정상 케이스에서 절대 드러나지 않는다.

- 모든 쿼리가 어차피 커밋되므로 결과만 보면 차이가 없다
- DB의 최종 상태는 트랜잭션이 정상 동작했을 때와 동일하다
- 단위 테스트도, 통합 테스트도, 수동 검증도 통과한다

차이가 드러나는 유일한 순간은 **예외가 발생해서 롤백이 필요한 시점**이다. 그 시점이 오기 전까지 이 코드는 "잘 동작하는 것처럼" 보인다. 사실은 트랜잭션 없이 실행되고 있던 것뿐인데.

이런 종류의 버그가 위험한 이유가 여기에 있다. **운영 장애가 1차 검증**이 되는 코드. 자동으로 감지할 수도 없고, 코드 리뷰로 잡기도 어렵고, 테스트로 잡으려면 실패 경로를 의도적으로 만들어야 한다.

## 9. 픽스, 그리고 그 한계

이 문제에 대한 픽스는 단순했다. `transactionManagerLive`도 `JpaTransactionManager`로 통일하는 것이었다.

```java
// Before
public DataSourceTransactionManager transactionManagerLive(DataSource dataSource) {
    return new DataSourceTransactionManager(dataSource);
}

// After
public PlatformTransactionManager transactionManagerLive(EntityManagerFactory emf) {
    JpaTransactionManager tm = new JpaTransactionManager();
    tm.setEntityManagerFactory(emf);
    tm.setNestedTransactionAllowed(true);
    return tm;
}
```

양쪽 매니저 타입을 동일하게 맞춰서, 어떤 매니저를 지정하든 같은 방식으로 동작하게 한다는 의도다.

그런데 이 픽스를 자세히 보면 조금 미심쩍은 부분이 있다. 5절에서 정리한 `JpaTransactionManager.doBegin()`의 ThreadLocal 바인딩 조건을 다시 보자.

1. `setDataSource()`가 호출되어야 한다
2. `JpaDialect.getJdbcConnection()`이 non-null을 반환해야 한다

위 픽스 코드에는 `setEntityManagerFactory()`만 있고 **`setDataSource()` 호출이 없다.** 즉 조건 1을 만족하지 않는다. 조건 1을 통과하지 못하면 doBegin에서 ThreadLocal 바인딩 시도 자체가 일어나지 않는다.

이론상으로는 픽스 후에도 MyBatis-only 메서드 (혹은 JPA가 메서드 끝에만 있는 메서드) 에서 같은 함정이 재발할 수 있다. 정확한 동작을 확인하려면 픽스 후 환경에서 다시 시뮬레이션 테스트가 필요하다.

PR 리뷰 과정도 살펴봤지만, 위의 시나리오를 명시적으로 검증한 흔적이 없었다. 테스트 시나리오는 "MyBatis만 / JPA만 / 혼합" 세 가지로만 구분되어 있고, 호출 순서나 예외 위치는 명시되지 않았다. 이런 상태로 머지된 픽스는 **표면 증상은 가렸지만, 동일한 함정이 다른 메서드에서 재발할 가능성**을 남겨둔다.

이 픽스가 잘못되었다고 단정하려는 건 아니다. 다만 **검증되지 않은 부분이 명확히 존재하고, 그 부분이 원래 버그의 핵심 메커니즘과 동일하다**는 점은 분명하다.

## 10. 진짜 교훈 — 두 ORM을 섞지 말 것

여기까지 추적해보면 자연스럽게 떠오르는 질문이 있다.

> 애초에 JPA와 MyBatis를 한 트랜잭션 안에서 같이 쓰지 않았다면, 이 함정 자체가 존재하지 않았을 것 아닌가?

정확히 그렇다. 그리고 이게 이 사례의 진짜 교훈이라고 생각한다.

두 ORM을 한 프로젝트에서, 더 나아가 한 메서드에서 함께 사용하는 순간 다음과 같은 부담이 추가된다.

- **호출 순서에 따라 동작이 달라진다** — JPA를 먼저 호출하느냐 MyBatis를 먼저 호출하느냐가 트랜잭션 동작을 결정한다
- **검증이 어렵다** — 정상 케이스로는 함정을 발견할 수 없고, 실패 경로를 의도적으로 만들어야 한다
- **이해해야 할 것이 많다** — `JpaTransactionManager`, `TransactionSynchronizationManager`, `DataSourceUtils`, Hibernate의 lazy connection 전략, HikariCP의 autoCommit 동작, JpaDialect의 구현체별 차이까지 모두 알아야 한다
- **함정을 하나 막아도 다른 함정이 남는다** — 트랜잭션 매니저 통일은 한 가지 패턴을 막을 뿐, 영속성 캐시 정합성 같은 또 다른 함정은 그대로 남는다

게다가 두 ORM을 같이 쓰면 영속성 캐시 정합성 문제도 생긴다. JPA가 1차 캐시에 들고 있는 엔티티를 MyBatis가 직접 UPDATE 해버리면, JPA는 그 변경을 모르고 캐시된 옛날 값을 반환할 수 있다. 트랜잭션 함정과는 또 다른 종류의 함정이다.

## 11. 마무리 — 추상화의 비용

이 사례를 통해 생각해볼 수 있는 더 큰 질문이 있다. **추상화는 공짜인가?**

`@Transactional` 어노테이션 한 줄은 매우 강력한 추상화다. 트랜잭션 시작, 커넥션 관리, 예외 시 롤백, 정상 종료 시 커밋 — 이 모든 복잡한 동작을 한 줄로 표현한다. 일반적인 상황에서는 이 추상화가 잘 동작한다.

하지만 추상화 계층이 늘어나거나, 서로 다른 추상화 (JPA + MyBatis) 가 한 컨텍스트에서 만나면, 그 사이의 미묘한 동작 차이가 함정을 만든다. 그리고 이 함정은 평소엔 보이지 않다가 장애 시점에 한꺼번에 모습을 드러낸다.

추상화의 비용은 작성 시점이 아니라 디버깅 시점에 청구된다. 그리고 그 비용은 종종 운영 장애의 형태로 온다.

이번 사례에서 가장 인상적이었던 부분은, **감사 로그를 추가하기 위해 만든 변경**이 트랜잭션을 깨뜨리는 원인이 되었다는 점이다. 안전망을 추가한 결과 안전망 자체가 무너졌다. 추상화 계층이 만든 보이지 않는 의존성이 가져온 결과다.

다음 글에서는 이 관점을 더 확장해서, **에이전틱 코딩 시대에 영속성 계층을 어떻게 선택할 것인가**에 대해 이야기해볼 생각이다.

---

## 부록: 확인이 필요한 항목

이 글을 더 정확하게 만들기 위해 검증이 필요한 부분이 있다.

- 픽스 후 환경에서 MyBatis-only 메서드의 트랜잭션 롤백이 실제로 동작하는지
- `HibernateJpaDialect.getJdbcConnection()`이 lazy 모드에서 항상 null을 반환하는지
- `JpaTransactionManager`에 `setDataSource()`를 함께 호출하는 설정이 다른 환경에 존재하는지

이 부분은 후속 검증을 통해 보강할 예정이다.
