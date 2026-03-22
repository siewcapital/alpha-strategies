"""
StatArb Alpha: Signal Generation Module
This module handles the logic for generating entry and exit signals.
"""

import numpy as np
from typing import Dict, List, Tuple

class SignalGenerator:
    def __init__(self, z_threshold: float = 2.0, exit_threshold: float = 0.0, stop_z: float = 4.0):
        self.z_threshold = z_threshold
        self.exit_threshold = exit_threshold
        self.stop_z = stop_z
        self.current_position = 0  # 1: Long Spread (Buy X, Sell Y), -1: Short Spread (Sell X, Buy Y), 0: Neutral

    def generate_signal(self, current_z: float) -> Tuple[int, str]:
        """
        Determine trade signal based on the current Z-score.
        :param current_z: The current Z-score of the spread.
        :return: (Signal (1, -1, 0), Reason)
        """
        if self.current_position == 0:
            # Not in a position, check for entry
            if current_z > self.z_threshold:
                # Spread is too high, Sell X, Buy Y (Short the spread)
                self.current_position = -1
                return -1, "Entry: Z-Score > 2.0 (Short Spread)"
            elif current_z < -self.z_threshold:
                # Spread is too low, Buy X, Sell Y (Long the spread)
                self.current_position = 1
                return 1, "Entry: Z-Score < -2.0 (Long Spread)"
        else:
            # Currently in a position, check for exit
            if self.current_position == 1:
                # Long Spread: PriceX - PriceY too low
                if current_z >= self.exit_threshold:
                    # Mean reverted
                    self.current_position = 0
                    return 0, "Exit: Reversion to Mean"
                elif current_z <= -self.stop_z:
                    # Divergence risk
                    self.current_position = 0
                    return 0, "Exit: Stop Loss (Extreme Divergence)"
            elif self.current_position == -1:
                # Short Spread: PriceX - PriceY too high
                if current_z <= self.exit_threshold:
                    # Mean reverted
                    self.current_position = 0
                    return 0, "Exit: Reversion to Mean"
                elif current_z >= self.stop_z:
                    # Divergence risk
                    self.current_position = 0
                    return 0, "Exit: Stop Loss (Extreme Divergence)"
                    
        return self.current_position, "Maintain Position"

    def reset(self):
        """Reset the signal state."""
        self.current_position = 0
