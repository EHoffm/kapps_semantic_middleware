from aas_middleware import AasMiddleware


class SemanticMiddleware(AasMiddleware):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)