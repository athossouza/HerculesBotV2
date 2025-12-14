
import re

def validate_password(password: str) -> bool:
    """
    Validates the password for restricted access.
    Hardcoded rule: must be exactly "102938".
    """
    if not password:
        return False
    # Normalize input: strip whitespace
    return password.strip() == "102938"

def validate_serial_format(serial: str) -> bool:
    """
    Validates that the serial number is numeric and exactly 19 digits.
    """
    if not serial:
        return False
    serial = serial.strip()
    return bool(re.fullmatch(r"^\d{19}$", serial))

def check_serial_age(serial: str) -> bool:
    """
    Checks the age rule based on the 10th digit (1-indexed).
    If 10th digit (index 9) is:
      - 1 or 2 (< 3): Returns False (Too old, handoff)
      - >= 3: Returns True (Allowed)
    
    Assumes validate_serial_format has already passed.
    """
    # Defensive check
    if not validate_serial_format(serial):
        return False
        
    try:
        # Get 10th digit (index 9)
        tenth_digit = int(serial[9])
        if tenth_digit < 3:
            return False # Old motor
        return True # OK
    except (IndexError, ValueError):
        return False
