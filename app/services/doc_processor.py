import io
from typing import Optional, List, Dict
import logging

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

logger = logging.getLogger(__name__)

def extract_text_from_file(file_bytes: bytes, file_name: str) -> Optional[str]:
    """
    Extracts text from a file based on its extension.
    Supports .txt and .pdf (if pypdf is installed).
    """
    if file_name.endswith(".txt"):
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return file_bytes.decode("latin-1")
            except Exception as e:
                logger.error(f"Error decoding TXT file {file_name}: {e}")
                return None
    
    elif file_name.endswith(".pdf"):
        if not PYPDF_AVAILABLE:
            return "ERROR: PDF processing library (pypdf) is not installed. Please contact your administrator."
        
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                # 'layout=True' helps preserve the visual structure of tables and columns
                page_text = page.extract_text(extraction_mode="layout")
                if page_text:
                    text_parts.append(page_text)
            
            # Combine and clean up excessive empty lines that occur during layout extraction
            full_text = "\n\n".join(text_parts)
            import re
            # Replace 3+ newlines with 2 to keep sections separate but compact
            cleaned_text = re.sub(r'\n{3,}', '\n\n', full_text)
            return cleaned_text
        except Exception as e:
            logger.error(f"Error extracting text from PDF {file_name}: {e}")
            return None
            
    return None


def chunk_text(text: str, source_name: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> List[Dict]:
    """
    Splits a block of text into overlapping chunks suitable for embedding.

    Args:
        text:        The raw text to split.
        source_name: Label for the source (file path, URL, etc.) stored in each chunk.
        chunk_size:  Target character length per chunk.
        chunk_overlap: Characters of overlap between consecutive chunks.

    Returns:
        List of dicts: [{"file_path": str, "content": str, "chunk_index": int}, ...]
    """
    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_content = text[start:end].strip()
        if chunk_content:
            chunks.append({
                "file_path": source_name,
                "content": chunk_content,
                "chunk_index": chunk_index,
            })
            chunk_index += 1
        if end >= len(text):
            break
        start += chunk_size - chunk_overlap

    return chunks

