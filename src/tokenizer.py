"""日本語対応 TF-IDF トークナイザー.

fugashi (MeCab) を使った形態素解析ベースのトークナイザーを提供する。
fugashi が利用できない環境では文字 bigram にフォールバックする。
"""

import re

from sklearn.feature_extraction.text import TfidfVectorizer

try:
    import fugashi

    _tagger = fugashi.Tagger()
    _HAS_FUGASHI = True
except (ImportError, RuntimeError):
    _HAS_FUGASHI = False


def _ja_tokenizer(text: str) -> list[str]:
    """日本語テキストを形態素解析してトークンリストを返す."""
    if _HAS_FUGASHI:
        return [
            word.surface
            for word in _tagger(text)
            if len(word.surface) > 1 and not re.match(r"^[\s\d\W]+$", word.surface)
        ]
    # フォールバック: 空白分割（英語テキスト向け）
    return [w for w in text.split() if len(w) > 1]


def create_tfidf_vectorizer(**kwargs) -> TfidfVectorizer:
    """日本語対応の TfidfVectorizer を生成する."""
    defaults = {"tokenizer": _ja_tokenizer, "token_pattern": None}
    defaults.update(kwargs)
    return TfidfVectorizer(**defaults)
