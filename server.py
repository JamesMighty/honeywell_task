import argparse
from logging import DEBUG, ERROR, INFO, WARNING

from server_src.server_impl import Server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                    prog='server.py',
                    description='File transfer server')
    parser.add_argument("host",
                        help="IP address or hostname")
    parser.add_argument("port",
                        help="listening port",
                        type=int)
    parser.add_argument("--root-dir",
                        help="download root dir",
                        required=False,
                        default="./",
                        type=str)
    parser.add_argument("--buffsize",
                        required=False,
                        default=1024,
                        help="buffer size for basic communication",
                        type=int)
    parser.add_argument("--file-block-size",
                        required=False,
                        default=65535,
                        help="file block size in bytes (65535 max)",
                        type=int)

    choices = ["DEBUG", "INFO", "WARNING", "ERROR"]
    parser.add_argument("--log-level",
                        required=False,
                        default=INFO,
                        choices=[DEBUG, INFO, WARNING, ERROR],
                        help=f"Logging level, choices resp.: {", ".join(choices)}",
                        type=int)

    args = parser.parse_args()
    server = Server(args.host, args.port, args.buffsize, args.file_block_size, args.root_dir, args.log_level)
    server.start()
