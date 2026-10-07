"""Allow-list of tools. If a tool is not registered here the agent cannot call it. There is deliberately NO delete tool."""

from app.tools.base import Tool
from app.tools.read_tools import ClassifyDocument, FindDuplicates, ListFiles, ReadFile, SearchDocuments, SummarizeText
from app.tools.write_tools import MoveFile, RenameFile, WriteReport

ALL_TOOLS: tuple[type[Tool], ...] = (
    ListFiles,
    ReadFile,
    SearchDocuments,
    ClassifyDocument,
    SummarizeText,
    FindDuplicates,
    WriteReport,
    MoveFile,
    RenameFile,
)


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {t.name: t() for t in ALL_TOOLS}

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def names(self) -> list[str]:
        return list(self.tools)
