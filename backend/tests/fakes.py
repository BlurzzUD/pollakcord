from dataclasses import dataclass

from app.integrations.kreta.adapter import KretaOutcome, KretaResult


@dataclass
class FakeSession:
    username: str
    aborted: bool = False


class FakeKretaAdapter:
    def __init__(self) -> None:
        self.accounts = {
            "diak1": ("jelszo-egy", None, "Kiss Éva"),
            "diak2": ("jelszo-ketto", "123456", "Nagy Péter"),
            "diak3": ("jelszo-harom", None, "Tóth Anna"),
            "diak4": ("jelszo-negy", None, "Szabó Bence"),
            "diak5": ("jelszo-ot", None, "Varga Dóra"),
            "diak6": ("jelszo-hat", None, "Horváth Máté"),
        }
        self.sessions: list[FakeSession] = []
        self.seen_passwords: list[str] = []

    def lookup(self, username: str):
        if username in self.accounts:
            return self.accounts[username]
        if username.startswith("user") and username[4:].isdigit():
            number = username[4:]
            return (f"pw-{number}", None, f"Teszt Elek{number}")
        return None

    async def start(self, username: str, password: str):
        self.seen_passwords.append(password)
        account = self.lookup(username)
        if account is None or account[0] != password:
            return None, KretaResult(KretaOutcome.INVALID_CREDENTIALS)
        if account[1]:
            session = FakeSession(username)
            self.sessions.append(session)
            return session, KretaResult(KretaOutcome.TWO_FACTOR_REQUIRED)
        return None, KretaResult(KretaOutcome.IDENTIFIED, account[2])

    async def submit_two_factor(self, session: FakeSession, code: str):
        account = self.lookup(session.username)
        session.aborted = True
        if code == account[1]:
            return KretaResult(KretaOutcome.IDENTIFIED, account[2])
        return KretaResult(KretaOutcome.INVALID_TWO_FACTOR)

    async def abort(self, session) -> None:
        if session is not None:
            session.aborted = True
