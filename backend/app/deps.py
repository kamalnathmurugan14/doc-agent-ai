"""Wires services together."""

from app.adapters.classifier import Classifier, build_classifier
from app.adapters.llm import ChatLLM, OllamaChat
from app.adapters.retriever import Retriever, build_retriever
from app.config import Settings
from app.db.session import init_db
from app.services.approval_service import ApprovalManager
from app.services.run_service import RunManager
from app.tools.registry import Registry


class Container:
    def __init__(
        self,
        settings: Settings,
        llm: ChatLLM | None = None,
        retriever: Retriever | None = None,
        classifier: Classifier | None = None,
    ) -> None:
        self.settings = settings
        settings.docs_root.mkdir(parents=True, exist_ok=True)
        init_db(settings.db_path)
        self.llm = llm or OllamaChat(settings)
        self.retriever = retriever or build_retriever(settings)
        self.classifier = classifier or build_classifier(settings)
        self.registry = Registry()
        self.approvals = ApprovalManager(settings)
        self.runs = RunManager(settings, self.registry, self.llm, self.retriever, self.classifier, self.approvals)
        self.runs.recover()
