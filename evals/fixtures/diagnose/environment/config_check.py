import os


def service_url() -> str:
    return os.environ["SERVICE_URL"]


if __name__ == "__main__":
    print(service_url())
