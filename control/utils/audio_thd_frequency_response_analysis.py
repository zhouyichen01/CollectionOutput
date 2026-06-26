import numpy as np
from scipy.ndimage import maximum_filter


class AudioThdFrequencyResponseAnalysis(object):
    @staticmethod
    def spl_calculation(recorded_signal, reference_pressure=20e-6, window_size=1201, is_smooth=True):
        """
            计算录音信号的声压级（SPL）。

            参数:
                - recorded_signal : ndarray
                    输入的录音信号
                - reference_pressure : float
                    参考声压，默认为 20 μPa (20e-6 Pa)，用于 SPL 计算的基准
                - window_size: int
                    滑动窗口长度
                - is_smooth: bool
                    是否进行平滑处理，默认为 True

            返回:
                - spl_smooth : ndarray
                    经过平滑处理后的 SPL（单位 dB）
        """
        # 取绝对值并用最大值滤波器做平滑，获取每个窗口内的最大幅值
        amplitude_list = maximum_filter(np.abs(recorded_signal), size=window_size)
        # SPL 计算公式：20 * log10(幅值 / 参考声压)
        eps = 1e-20  # 极小值，避免除零
        amplitude_list = np.maximum(amplitude_list, eps)
        spl = 20 * np.log10(np.array(amplitude_list) / reference_pressure)
        if is_smooth:
            spl_smooth = np.convolve(spl, np.ones(1102) / 1102, mode='same')
            return spl_smooth
        else:
            return spl
