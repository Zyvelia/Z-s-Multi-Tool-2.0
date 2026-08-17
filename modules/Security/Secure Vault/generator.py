import random
import string


class PasswordGenerator:

    @staticmethod
    def generate(
        length=20,
        uppercase=True,
        lowercase=True,
        numbers=True,
        symbols=True
    ):

        chars = ""

        if uppercase:
            chars += string.ascii_uppercase

        if lowercase:
            chars += string.ascii_lowercase

        if numbers:
            chars += string.digits

        if symbols:
            chars += "!@#$%^&*()_+-=[]{}<>?/"

        if not chars:
            return ""

        return "".join(
            random.choice(chars)
            for _ in range(length)
        )

    @staticmethod
    def get_strength(password):

        score = 0

        if len(password) >= 8:
            score += 1

        if len(password) >= 12:
            score += 1

        if len(password) >= 16:
            score += 1

        if any(c.isupper() for c in password):
            score += 1

        if any(c.islower() for c in password):
            score += 1

        if any(c.isdigit() for c in password):
            score += 1

        if any(
            c in "!@#$%^&*()_+-=[]{}<>?/"
            for c in password
        ):
            score += 1

        if score <= 2:
            return "Weak"

        elif score <= 4:
            return "Medium"

        elif score <= 6:
            return "Strong"

        return "Very Strong"