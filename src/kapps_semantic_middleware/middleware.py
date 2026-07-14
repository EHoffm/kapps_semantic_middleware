from aas_middleware import Middleware


class SemanticMiddleware(Middleware):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


def main():
    middleware = SemanticMiddleware()
    print(middleware)
    middleware.add_callback


if __name__ == "__main__":
    main()
    

