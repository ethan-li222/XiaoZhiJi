from .config import Settings


class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    @property
    def identity(self):
        return str(self.settings.embedding_dir.resolve())

    def load(self):
        if not self.settings.embedding_dir.exists():
            raise ValueError("本地嵌入模型未初始化；运行 research-agent embeddings init")
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                str(self.settings.embedding_dir), device="cpu", local_files_only=True
            )
        return self._model

    def encode(self, texts, query=False):
        prefix = "query: " if query else "passage: "
        return self.load().encode([prefix + t for t in texts], normalize_embeddings=True).tolist()

    def initialize(self):
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self.settings.embedding_model, device="cpu")
        model.save(str(self.settings.embedding_dir))
        self._model = model
        return str(self.settings.embedding_dir)
