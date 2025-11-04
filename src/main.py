from app import App


if __name__ == "__main__":
    try:
        app = App()
        app.run()
    except KeyboardInterrupt:
        pass

