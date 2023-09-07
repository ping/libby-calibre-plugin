from enum import Enum


class StringEnum(str, Enum):
    # StrEnum is only available in 3.11.
    def __str__(self):
        return str(self.value)
