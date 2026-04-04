"""日本語ペインキーワード定義."""

import re

PAIN_KEYWORDS_JA = re.compile(
    r"(つらい|辛い|困っ|不便|面倒|めんどう|ストレス|イライラ|いらいら|"
    r"なんとかして|どうにか|不満|改善|解決|悩み|悩んで|苦労|苦しい|"
    r"使いにくい|わかりにくい|高すぎ|遅すぎ|ひどい|最悪|ダメ|だめ|"
    r"やめて|うんざり|嫌い|きらい|無理|ムリ|限界|疲れ|しんどい|"
    r"なぜできない|どうして|おかしい|バグ|壊れ|動かない|できない|"
    r"時間の無駄|もったいない|非効率|手間|手作業|自動化したい)",
    re.IGNORECASE,
)

MONETIZATION_KEYWORDS_JA = re.compile(
    r"(お金を払ってでも|課金したい|有料でもいい|有料でも使う|"
    r"月額.{0,10}払う|サブスク.{0,10}欲しい|買い切り.{0,10}欲しい|"
    r"いくらでも出す|高くても.{0,10}使いたい|"
    r"お金かかってもいい|金出してでも|"
    r"worth paying|shut up and take my money|"
    r"would pay|gladly pay|take my money)",
    re.IGNORECASE,
)


def contains_pain_keyword(text: str) -> bool:
    """テキストに日本語ペインキーワードが含まれるか判定する."""
    return bool(PAIN_KEYWORDS_JA.search(text))


def contains_monetization_signal(text: str) -> bool:
    """テキストに課金意欲を示すキーワードが含まれるか判定する."""
    return bool(MONETIZATION_KEYWORDS_JA.search(text))
