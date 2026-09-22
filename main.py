import json
from pathlib import Path

from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.Exceptions import CardConnectionException

from set_wallpaper import set_wallpaper


GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
TAGS_FILE = Path("data/tags.json")

CHARACTER_WALLPAPERS = {
    "Twilight Sparkle": "MLP_Wallpaper/Twilight.png",
    "Rainbow Dash": "MLP_Wallpaper/RainbowDash.png",
    "Pinkie Pie": "MLP_Wallpaper/PinkiePie.png",
    "Applejack": "MLP_Wallpaper/AppleJack.png",
    "Rarity": "MLP_Wallpaper/Rarity.png",
    "Fluttershy": "MLP_Wallpaper/Fluttershy.png",
}


def load_tags():
    """Load registered NFC tags from disk."""
    if not TAGS_FILE.exists():
        return {}

    with TAGS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_tags(tags):
    """Save registered NFC tags to disk."""
    TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with TAGS_FILE.open("w", encoding="utf-8") as file:
        json.dump(tags, file, indent=4)


class TagObserver(CardObserver):
    def __init__(self, tags):
        super().__init__()

        self.tags = tags
        self.character_to_register = None

    def register_next_tag(self, character_name):
        """Put the observer into registration mode."""
        self.character_to_register = character_name
        print(f"Scan tag for {character_name}...")

    def update(self, observable, handlers):
        added_cards, removed_cards = handlers

        for card in added_cards:
            try:
                connection = card.createConnection()
                connection.connect()

                data, sw1, sw2 = connection.transmit(GET_UID)

                # 0x90 0x00 means the command completed successfully.
                if (sw1, sw2) != (0x90, 0x00):
                    print(f"Failed to read UID: {sw1:02x} {sw2:02x}")
                    continue

                uid = "".join(format(byte, "02x") for byte in data)

                self.handle_tag(uid)

            except CardConnectionException as e:
                print(f"Failed to read tag: {e}")

        for card in removed_cards:
            print("Tag removed.")

    def handle_tag(self, uid):
        # Registration mode
        if self.character_to_register is not None:
            character = self.character_to_register

            self.tags[uid] = character
            save_tags(self.tags)

            print(f"Registered {character}: {uid}")

            # Return to normal listening mode.
            self.character_to_register = None
            return

        # Normal listening mode
        character = self.tags.get(uid)

        if character is None:
            print(f"Unknown tag: {uid}")
        else:
            print(f"Detected: {character}")

            wallpaper = CHARACTER_WALLPAPERS.get(character)
            if wallpaper is not None:
                print(f"Setting wallpaper for {character}...")
                set_wallpaper(wallpaper)
            print(f"Detected: {character}")


def main():
    tags = load_tags()

    print(f"Loaded {len(tags)} registered tag(s).")

    card_monitor = CardMonitor()
    tag_observer = TagObserver(tags)

    card_monitor.addObserver(tag_observer)

    print("DesktopPortal NFC listener started.")
    print("Commands: add, list, quit")

    try:
        while True:
            command = input("> ").strip().lower()

            if command == "add":
                character_name = input("Character name: ").strip()

                if not character_name:
                    print("Character name cannot be empty.")
                    continue

                tag_observer.register_next_tag(character_name)

            elif command == "list":
                if not tags:
                    print("No registered tags.")
                    continue

                for uid, character in tags.items():
                    print(f"{uid} -> {character}")

            elif command == "quit":
                break

            else:
                print("Unknown command. Use: add, list, quit")

    finally:
        card_monitor.deleteObserver(tag_observer)
        print("Bye!")


if __name__ == "__main__":
    main()