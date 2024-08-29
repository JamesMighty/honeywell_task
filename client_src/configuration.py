

import json
import os
from dataclasses import asdict, dataclass, field
from logging import INFO
from pathlib import Path

CONFIG_FILENAME = "client-config.json"


@dataclass
class Config:
    """Defines client configuration dataclass"""
    client_buffsize: int = 1024
    client_file_block_size: int = 1024*64-1
    log_level: int = INFO
    files: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)

    @staticmethod
    def _create_new_file() -> 'Config':
        config_path = Path(f"./{CONFIG_FILENAME}")
        defconf = Config()
        print(defconf)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(defconf), f, indent=4)
        return defconf

    @staticmethod
    def load() -> 'Config':
        """Static config loader method"""
        if not Config.get_path().exists():
            return Config._create_new_file()

        conf_raw: dict
        with open(Config.get_path(), "r", encoding="utf-8") as f:
            conf_raw = json.load(f)

        try:
            inst = Config(**conf_raw)
        except Exception as err:
            print(f"Could not load configuration, creating new: {err}")
            os.rename(Config.get_path(), Path(f"{Config.get_path()}.old"))
            return Config._create_new_file()

        return inst

    def save(self):
        """"Save config"""
        with open(Config.get_path(), 'w', encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4)

    @staticmethod
    def get_path() -> Path:
        """Get default config file path"""
        return Path(f"./{CONFIG_FILENAME}")
