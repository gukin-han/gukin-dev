"""
ECS Auto Scaling 블로그용 시뮬레이션 그래프
출퇴근 시간대 CPU 사용률 패턴 + 임계점 영역 표시

회사 운영 데이터가 아닌 시뮬레이션 데이터입니다.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from matplotlib import font_manager, rcParams

# 한글 폰트 설정 (macOS)
rcParams['font.family'] = 'AppleGothic'
rcParams['axes.unicode_minus'] = False


def generate_traffic_pattern():
    """B2B HR 서비스의 일일 CPU 사용률 시뮬레이션."""
    hours = np.linspace(0, 24, 240)

    # 기본 baseline (낮은 수준)
    baseline = 15

    # 출근 스파이크 (8~10시)
    morning_spike = 50 * np.exp(-((hours - 9) ** 2) / 1.2)

    # 점심 시간 약간의 활동 (12~14시)
    lunch = 15 * np.exp(-((hours - 13) ** 2) / 4)

    # 오후 정상 운영 (14~17시)
    afternoon = 20 * np.exp(-((hours - 15.5) ** 2) / 6)

    # 퇴근 스파이크 (18~19시)
    evening_spike = 55 * np.exp(-((hours - 18.5) ** 2) / 0.8)

    # 합산 + 약간의 노이즈
    cpu = baseline + morning_spike + lunch + afternoon + evening_spike
    np.random.seed(42)
    noise = np.random.normal(0, 2, len(hours))
    cpu += noise

    # 0~100 클리핑
    cpu = np.clip(cpu, 0, 100)

    return hours, cpu


def main():
    hours, cpu = generate_traffic_pattern()

    fig, ax = plt.subplots(figsize=(11, 5.5))

    # 배경 영역: 0~40% (정상)
    ax.axhspan(0, 40, alpha=0.15, color='#27ae60', label='정상 운영 (0~40%)')
    # 배경 영역: 40~70% (버퍼)
    ax.axhspan(40, 70, alpha=0.15, color='#f39c12', label='버퍼 구간 (40~70%)')
    # 배경 영역: 70~100% (Scale Out 트리거)
    ax.axhspan(70, 100, alpha=0.18, color='#e74c3c', label='Scale Out 트리거 (70%+)')

    # 임계선 (70%)
    ax.axhline(y=70, color='#c0392b', linestyle='--', linewidth=1.5, alpha=0.7)
    ax.text(0.3, 72, 'Scale Out 임계점 (70%)', color='#c0392b', fontsize=9, fontweight='bold')

    # baseline 목표선 (40%)
    ax.axhline(y=40, color='#1e8449', linestyle='--', linewidth=1.2, alpha=0.6)
    ax.text(0.3, 42, 'baseline 목표 (40%)', color='#1e8449', fontsize=9)

    # CPU 라인
    ax.plot(hours, cpu, color='#2c3e50', linewidth=2, label='CPU 사용률', zorder=10)

    # 스파이크 주석
    ax.annotate('출근 스파이크',
                xy=(9, 67), xytext=(6, 88),
                fontsize=10, color='#2c3e50', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#2c3e50', lw=1.2))
    ax.annotate('퇴근 스파이크',
                xy=(18.5, 72), xytext=(20, 90),
                fontsize=10, color='#2c3e50', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#2c3e50', lw=1.2))

    # 축 설정
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 100)
    ax.set_xticks(np.arange(0, 25, 3))
    ax.set_xticklabels([f'{int(h)}시' for h in np.arange(0, 25, 3)])
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_yticklabels([f'{int(y)}%' for y in np.arange(0, 101, 20)])

    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('CPU 사용률', fontsize=11)
    ax.set_title('일일 CPU 사용률 패턴 (시뮬레이션)\nB2B HR 서비스의 출퇴근 시간대 부하 분포',
                 fontsize=12, fontweight='bold', pad=15)

    # 격자
    ax.grid(True, alpha=0.3, linestyle=':')
    ax.set_axisbelow(True)

    # 범례
    ax.legend(loc='upper left', framealpha=0.9, fontsize=9)

    plt.tight_layout()

    # 저장
    output_path = '/Users/hangug-in/Desktop/workspace/personal/engineering-hub/topics/images/cpu_traffic_pattern.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f'저장 완료: {output_path}')


if __name__ == '__main__':
    main()
