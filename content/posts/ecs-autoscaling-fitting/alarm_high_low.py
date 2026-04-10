"""
ECS Auto Scaling 블로그용 시뮬레이션 그래프
AlarmHigh / AlarmLow 동작 비교

원본 CloudWatch 캡처를 참고했지만, 절대 수치는 다르게 잡은 시뮬레이션 데이터입니다.
회사 운영 데이터가 아닙니다.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import rcParams
from matplotlib.patches import Rectangle

rcParams['font.family'] = 'AppleGothic'
rcParams['axes.unicode_minus'] = False


def generate_load_pattern():
    """
    부하 테스트 시뮬레이션:
    - 초반 idle (10%)
    - 점진적 부하 상승 → 피크 (~85%)
    - 피크 유지
    - 부하 종료 후 빠른 하락
    """
    minutes = np.linspace(0, 90, 360)  # 0~90분, 15초 간격

    cpu = np.full_like(minutes, 10.0)

    for i, m in enumerate(minutes):
        if m < 15:
            cpu[i] = 10
        elif m < 25:
            # 점진적 상승
            cpu[i] = 10 + (m - 15) * 2.0
        elif m < 32:
            # 빠른 상승
            cpu[i] = 30 + (m - 25) * 8.0
        elif m < 45:
            # 피크 유지
            cpu[i] = 85
        elif m < 50:
            # scale out 효과로 하락
            cpu[i] = 85 - (m - 45) * 12
        else:
            cpu[i] = max(10, 25 - (m - 50) * 0.4)

    np.random.seed(7)
    noise = np.random.normal(0, 2.5, len(minutes))
    cpu += noise
    cpu = np.clip(cpu, 0, 100)

    return minutes, cpu


def find_sustained_above(values, threshold, count):
    """값이 threshold 이상으로 count개 연속된 첫 인덱스."""
    consecutive = 0
    for i, v in enumerate(values):
        if v > threshold:
            consecutive += 1
            if consecutive >= count:
                return i
        else:
            consecutive = 0
    return None


def find_sustained_below(values, threshold, count, start=0):
    """값이 threshold 미만으로 count개 연속된 첫 인덱스 (start부터 검색)."""
    consecutive = 0
    for i in range(start, len(values)):
        if values[i] < threshold:
            consecutive += 1
            if consecutive >= count:
                return i
        else:
            consecutive = 0
    return None


def plot_alarm_high(minutes, cpu, output_path):
    """
    AlarmHigh: CPU > 70%, 3분 / 3 datapoints
    트리거 → in alarm 유지 → CPU 하락 → OK 복귀의 사이클을 시각화.
    """
    fig, (ax_main, ax_state) = plt.subplots(
        2, 1, figsize=(11, 5),
        gridspec_kw={'height_ratios': [4, 0.5]},
        sharex=True
    )

    # CPU 라인
    ax_main.plot(minutes, cpu, color='#2980b9', linewidth=1.8, zorder=10)

    # 70% 임계선
    ax_main.axhline(y=70, color='#c0392b', linestyle='--', linewidth=1.3, alpha=0.7)
    ax_main.text(2, 73, 'Threshold: 70%', color='#c0392b', fontsize=9, fontweight='bold')

    # 알람 진입: 70% 초과 3분 연속 (15초 간격에서 12 datapoints = 3분)
    DATAPOINTS = 12  # 3분 = 12 datapoints
    ONE_MINUTE = 4   # 1분 = 4 datapoints (CloudWatch 1분 측정 간격 시뮬레이션)
    enter_idx = find_sustained_above(cpu, 70, DATAPOINTS)
    # 알람 해제: 진입 이후 CPU <= 70% 첫 datapoint + 1분 측정 지연
    exit_idx = None
    if enter_idx is not None:
        for i in range(enter_idx + 1, len(cpu)):
            if cpu[i] <= 70:
                exit_idx = min(i + ONE_MINUTE, len(cpu) - 1)
                break

    if enter_idx is not None and exit_idx is not None:
        enter_min = minutes[enter_idx]
        exit_min = minutes[exit_idx]

        # in alarm 영역 (빨간 음영)
        ax_main.axvspan(enter_min, exit_min, alpha=0.18, color='#e74c3c', zorder=1)

        # 진입 / 해제 전환 이벤트 점
        ax_main.scatter([enter_min, exit_min],
                        [cpu[enter_idx], cpu[exit_idx]],
                        color='black', s=80, zorder=15, label='상태 전환 이벤트')

        # 진입 주석
        ax_main.annotate('In alarm 진입\n(3 datapoints > 70%)',
                         xy=(enter_min, cpu[enter_idx]),
                         xytext=(enter_min - 18, 95),
                         fontsize=9.5, color='#c0392b', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.2))

        # 해제 주석
        ax_main.annotate('OK 복귀\n(CPU ≤ 70%, 즉시)',
                         xy=(exit_min, cpu[exit_idx]),
                         xytext=(exit_min + 5, 80),
                         fontsize=9.5, color='#16a085', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='#16a085', lw=1.2))

        # in alarm 지속 시간 표시
        duration = exit_min - enter_min
        ax_main.annotate(
            '', xy=(exit_min, 5), xytext=(enter_min, 5),
            arrowprops=dict(arrowstyle='<->', color='#7f8c8d', lw=1.5)
        )
        ax_main.text(
            (enter_min + exit_min) / 2, 9,
            f'In alarm 지속 {duration:.0f}분',
            fontsize=9.5, color='#34495e', ha='center', fontweight='bold'
        )

    # 축
    ax_main.set_ylim(0, 100)
    ax_main.set_xlim(0, 90)
    ax_main.set_yticks(np.arange(0, 101, 20))
    ax_main.set_yticklabels([f'{int(y)}%' for y in np.arange(0, 101, 20)])
    ax_main.set_ylabel('CPU 사용률', fontsize=11)
    ax_main.set_title(
        'AlarmHigh: CPU > 70% for 3 datapoints within 3 minutes\n(시뮬레이션)',
        fontsize=11, fontweight='bold', pad=12
    )
    ax_main.grid(True, alpha=0.3, linestyle=':')
    ax_main.set_axisbelow(True)
    ax_main.legend(loc='upper left', framealpha=0.9, fontsize=9)

    # 알람 상태 바: green → red → green
    ax_state.set_xlim(0, 90)
    ax_state.set_ylim(0, 1)
    ax_state.set_yticks([])

    if enter_idx is not None and exit_idx is not None:
        ax_state.add_patch(Rectangle((0, 0), enter_min, 1,
                                      facecolor='#a8d5a2', edgecolor='none'))
        ax_state.add_patch(Rectangle((enter_min, 0), exit_min - enter_min, 1,
                                      facecolor='#e74c3c', edgecolor='none'))
        ax_state.add_patch(Rectangle((exit_min, 0), 90 - exit_min, 1,
                                      facecolor='#a8d5a2', edgecolor='none'))
    else:
        ax_state.add_patch(Rectangle((0, 0), 90, 1,
                                      facecolor='#a8d5a2', edgecolor='none'))

    ax_state.set_xlabel('경과 시간 (분)', fontsize=10)
    ax_state.text(-3, 0.5, '알람\n상태', fontsize=9, ha='right', va='center')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'저장: {output_path}')


def plot_alarm_low(minutes, cpu, output_path):
    """
    AlarmLow: CPU < 63%, 15분 / 15 datapoints
    초기 in alarm → CPU 상승 → OK 복귀 → CPU 하락 → 15분 지연 후 in alarm 재진입.
    """
    fig, (ax_main, ax_state) = plt.subplots(
        2, 1, figsize=(11, 5),
        gridspec_kw={'height_ratios': [4, 0.5]},
        sharex=True
    )

    # CPU 라인
    ax_main.plot(minutes, cpu, color='#2980b9', linewidth=1.8, zorder=10)

    # 63% 임계선
    ax_main.axhline(y=63, color='#16a085', linestyle='--', linewidth=1.3, alpha=0.7)
    ax_main.text(2, 65, 'Threshold: 63%', color='#16a085', fontsize=9, fontweight='bold')

    DATAPOINTS = 60  # 15분 = 60 datapoints (15초 간격)
    ONE_MINUTE = 4   # 1분 = 4 datapoints (CloudWatch 1분 측정 간격 시뮬레이션)

    # 알람 상태 시뮬레이션 (CloudWatch 의미를 그대로 구현)
    # - 진입: 15분(60 datapoints) 연속 < 63%
    # - 해제: CPU >= 63% 첫 datapoint + 1분 측정 지연 (비대칭)
    # - 가정: 시작 시점 이전부터 CPU가 한참 낮은 상태였으므로 IN_ALARM으로 시작
    state = 'IN_ALARM'
    transitions = [(0.0, 'IN_ALARM')]
    consecutive_below = DATAPOINTS  # 시작 시점에 이미 조건 충족이라고 가정
    pending_exit_at = None  # 해제 예약 시점

    for i in range(len(cpu)):
        # 해제 지연 처리: 예약된 시점에 도달하면 OK로 전환
        if pending_exit_at is not None and i >= pending_exit_at:
            transitions.append((minutes[i], 'OK'))
            state = 'OK'
            pending_exit_at = None

        if cpu[i] < 63:
            consecutive_below += 1
            if state == 'OK' and consecutive_below >= DATAPOINTS:
                transitions.append((minutes[i], 'IN_ALARM'))
                state = 'IN_ALARM'
        else:
            consecutive_below = 0
            if state == 'IN_ALARM' and pending_exit_at is None:
                pending_exit_at = i + ONE_MINUTE  # 1분 후 해제 예약
    transitions.append((90.0, state))

    # 주요 이벤트 추출
    ok_return_min = None  # CPU > 63%로 처음 OK 복귀한 시점
    re_enter_min = None   # 다시 IN_ALARM 진입한 시점
    for t, s in transitions[1:]:
        if s == 'OK' and ok_return_min is None:
            ok_return_min = t
        elif s == 'IN_ALARM' and t > 0 and re_enter_min is None:
            re_enter_min = t

    # 피크 이후 처음 63% 미만으로 떨어진 시점 (점선 표시용)
    peak_idx = int(np.argmax(cpu))
    drop_idx = None
    for i in range(peak_idx, len(cpu)):
        if cpu[i] < 63:
            drop_idx = i
            break
    drop_min = minutes[drop_idx] if drop_idx is not None else None

    # in alarm 영역 음영 (transitions 기반)
    for i in range(1, len(transitions)):
        prev_t, prev_s = transitions[i - 1]
        curr_t, _ = transitions[i]
        if prev_s == 'IN_ALARM':
            ax_main.axvspan(prev_t, curr_t, alpha=0.18, color='#e74c3c', zorder=1)

    # OK 복귀 주석
    if ok_return_min is not None:
        ok_idx = int(np.searchsorted(minutes, ok_return_min))
        ax_main.scatter([ok_return_min], [cpu[ok_idx]],
                        color='black', s=70, zorder=15)
        ax_main.annotate('OK 복귀\n(CPU > 63%, 즉시)',
                         xy=(ok_return_min, cpu[ok_idx]),
                         xytext=(ok_return_min - 14, 50),
                         fontsize=9, color='#16a085', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='#16a085', lw=1.2))

    # 63% 미만 재진입 점선
    if drop_min is not None:
        ax_main.axvline(x=drop_min, color='#7f8c8d', linestyle=':',
                        linewidth=1.2, alpha=0.7)
        ax_main.text(drop_min + 0.4, 95, '63% 미만\n재진입',
                     fontsize=8.5, color='#7f8c8d', style='italic')

    # In alarm 재진입 + 지연 시간
    if re_enter_min is not None and drop_min is not None:
        re_idx = int(np.searchsorted(minutes, re_enter_min))
        ax_main.scatter([re_enter_min], [cpu[re_idx]],
                        color='black', s=70, zorder=15, label='상태 전환 이벤트')
        ax_main.annotate('In alarm 재진입\n(15분 지속)',
                         xy=(re_enter_min, cpu[re_idx]),
                         xytext=(re_enter_min + 2, 55),
                         fontsize=9, color='#c0392b', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.2))

        delay = re_enter_min - drop_min
        ax_main.annotate(
            '', xy=(re_enter_min, 5), xytext=(drop_min, 5),
            arrowprops=dict(arrowstyle='<->', color='#7f8c8d', lw=1.5)
        )
        ax_main.text(
            (drop_min + re_enter_min) / 2, 9,
            f'지연 {delay:.0f}분',
            fontsize=9.5, color='#34495e', ha='center', fontweight='bold'
        )

    # 축
    ax_main.set_ylim(0, 100)
    ax_main.set_xlim(0, 90)
    ax_main.set_yticks(np.arange(0, 101, 20))
    ax_main.set_yticklabels([f'{int(y)}%' for y in np.arange(0, 101, 20)])
    ax_main.set_ylabel('CPU 사용률', fontsize=11)
    ax_main.set_title(
        'AlarmLow: CPU < 63% for 15 datapoints within 15 minutes\n(시뮬레이션)',
        fontsize=11, fontweight='bold', pad=12
    )
    ax_main.grid(True, alpha=0.3, linestyle=':')
    ax_main.set_axisbelow(True)
    ax_main.legend(loc='upper right', framealpha=0.9, fontsize=9)

    # 알람 상태 바: transitions 기반으로 그림
    ax_state.set_xlim(0, 90)
    ax_state.set_ylim(0, 1)
    ax_state.set_yticks([])

    for i in range(1, len(transitions)):
        prev_t, prev_s = transitions[i - 1]
        curr_t, _ = transitions[i]
        color = '#e74c3c' if prev_s == 'IN_ALARM' else '#a8d5a2'
        ax_state.add_patch(Rectangle((prev_t, 0), curr_t - prev_t, 1,
                                      facecolor=color, edgecolor='none'))

    ax_state.set_xlabel('경과 시간 (분)', fontsize=10)
    ax_state.text(-3, 0.5, '알람\n상태', fontsize=9, ha='right', va='center')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'저장: {output_path}')


def plot_scale_out_result(output_path):
    """
    Scale Out 결과 시뮬레이션:
    실제 관찰 패턴을 참고한 시뮬레이션.
    - 초기 idle (~1%)
    - 부하 시작 → CPU 급등 (~93-97%)
    - Scale out 트리거 → 새 태스크 생성
    - 2대 안착 후 CPU ~49-52% 안정화
    """
    minutes = np.linspace(0, 40, 160)  # 0~40분, 15초 간격
    cpu = np.full_like(minutes, 1.0)

    for i, m in enumerate(minutes):
        if m < 1:
            # idle (테스트 서버 기본 부하)
            cpu[i] = 3
        elif m < 3:
            # 부하 시작 → 급등
            cpu[i] = 3 + (m - 1) * 46
        elif m < 11:
            # 피크 유지 (~93-97%) - 알람 트리거(3분) + 태스크 생성/부팅(~5분)
            cpu[i] = 95
        elif m < 14:
            # scale out 효과 → CPU 하락
            cpu[i] = 95 - (m - 11) * 15
        elif m <= 40:
            # 2대 안착 후 안정화 (~49%)
            cpu[i] = 49

    # 노이즈
    np.random.seed(12)
    noise = np.random.normal(0, 2.0, len(minutes))
    cpu += noise
    cpu = np.clip(cpu, 0, 100)

    fig, ax = plt.subplots(figsize=(11, 5))

    # CPU 라인
    ax.plot(minutes, cpu, color='#2980b9', linewidth=1.8, zorder=10)

    # 70% 임계선
    ax.axhline(y=70, color='#c0392b', linestyle='--', linewidth=1.3, alpha=0.7)
    ax.text(1, 73, 'Threshold: 70%', color='#c0392b', fontsize=9, fontweight='bold')

    # 안정화 라인 (~49%)
    ax.axhline(y=49, color='#16a085', linestyle=':', linewidth=1.2, alpha=0.6)
    ax.text(25, 51.5, '안정화: ~49%', color='#16a085', fontsize=9, fontweight='bold')

    # 주석: 부하 시작
    ax.annotate('부하 시작\n(80 threads)',
                xy=(2, 50), xytext=(4, 65),
                fontsize=9, color='#2c3e50', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#2c3e50', lw=1.2))

    # 주석: 피크
    ax.annotate('CPU ~93%\n(1대)',
                xy=(7, 95), xytext=(9, 85),
                fontsize=9, color='#c0392b', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.2))

    # 주석: scale out 효과
    ax.annotate('Scale out 완료\n2대 안착',
                xy=(17, 49), xytext=(20, 70),
                fontsize=9, color='#16a085', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#16a085', lw=1.2))

    # 피크 영역 음영
    ax.axvspan(3, 11, alpha=0.1, color='#e74c3c', zorder=1)

    # 축
    ax.set_ylim(0, 100)
    ax.set_xlim(0, 40)
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_yticklabels([f'{int(y)}%' for y in np.arange(0, 101, 20)])
    ax.set_xlabel('경과 시간 (분)', fontsize=10)
    ax.set_ylabel('CPU 사용률', fontsize=11)
    ax.set_title(
        'Scale Out 후 CPU 안정화 (시뮬레이션)\n1대 → 2대 안착 후 부하 균등 분배',
        fontsize=11, fontweight='bold', pad=12
    )
    ax.grid(True, alpha=0.3, linestyle=':')
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'저장: {output_path}')


def main():
    minutes, cpu = generate_load_pattern()

    base = '/Users/hangug-in/Desktop/workspace/personal/gukin-dev/content/posts/ecs-autoscaling-fitting'
    plot_alarm_high(minutes, cpu, f'{base}/alarm_high.png')
    plot_alarm_low(minutes, cpu, f'{base}/alarm_low.png')
    plot_scale_out_result(f'{base}/scale_out_result.png')


if __name__ == '__main__':
    main()
