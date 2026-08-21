"""Channel layer: CLI. Fastest way to poke at the agent without spinning up
the web UI -- same orchestrator underneath as the web channel."""
from app.memory import Session
from app.orchestrator import run_turn


def main():
    print("Bookly Support (CLI) -- type 'exit' to quit.\n")
    session = Session()
    while True:
        try:
            user_message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_message:
            continue
        if user_message.lower() in {"exit", "quit"}:
            break
        reply = run_turn(session, user_message)
        print(f"bookly> {reply}\n")


if __name__ == "__main__":
    main()
