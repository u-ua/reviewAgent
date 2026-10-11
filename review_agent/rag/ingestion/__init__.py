"""权威知识源的快照、解析与语义切分。"""

from .cwe_parser import parse_cwe_xml
from .models import KnowledgeChunk, SourceSnapshot

__all__ = ["KnowledgeChunk", "SourceSnapshot", "parse_cwe_xml"]
