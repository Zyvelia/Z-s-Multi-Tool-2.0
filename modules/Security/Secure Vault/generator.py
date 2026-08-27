import secrets
import string

SYMBOLS = "!@#$%^&*()_+-=[]{}?/"
AMBIGUOUS = set("0O1lI|")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class PasswordGenerator:

    @staticmethod
    def generate(
        length=20,
        uppercase=True,
        lowercase=True,
        numbers=True,
        symbols=True,
        exclude_ambiguous=False,
    ) -> str:
        pools: list[str] = []
        if uppercase:
            pools.append(string.ascii_uppercase)
        if lowercase:
            pools.append(string.ascii_lowercase)
        if numbers:
            pools.append(string.digits)
        if symbols:
            pools.append(SYMBOLS)

        if not pools:
            return ""

        length = max(MIN_PASSWORD_LENGTH, min(MAX_PASSWORD_LENGTH, int(length)))

        if exclude_ambiguous:
            pools = ["".join(c for c in pool if c not in AMBIGUOUS) for pool in pools]
            pools = [pool for pool in pools if pool]
            if not pools:
                return ""

        length = max(len(pools), int(length))
        rng = secrets.SystemRandom()

        chars = [rng.choice(pool) for pool in pools]
        alphabet = "".join(pools)
        while len(chars) < length:
            chars.append(rng.choice(alphabet))
        rng.shuffle(chars)
        return "".join(chars)

    @staticmethod
    def strength_score(password: str) -> int:
        if not password:
            return 0

        score = 0
        length = len(password)
        if length >= 8:
            score += 1
        if length >= 12:
            score += 1
        if length >= 16:
            score += 1
        if length >= 20:
            score += 1
        if any(c.isupper() for c in password):
            score += 1
        if any(c.islower() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(c in SYMBOLS for c in password):
            score += 1

        unique_ratio = len(set(password)) / length
        if unique_ratio >= 0.6:
            score += 1

        return min(100, int(score / 9 * 100))

    @staticmethod
    def get_strength(password: str) -> str:
        score = PasswordGenerator.strength_score(password)
        if score < 35:
            return "Weak"
        if score < 55:
            return "Medium"
        if score < 75:
            return "Strong"
        return "Very Strong"
