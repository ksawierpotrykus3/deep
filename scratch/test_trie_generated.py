from __future__ import annotations
from typing import Optional
import unittest


class TrieNode:
    """Reprezentuje pojedynczy węzeł w strukturze drzewa Trie."""

    __slots__ = ("children", "is_end_of_word", "frequency")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.is_end_of_word: bool = False
        self.frequency: int = 0


class AutocompleteTrie:
    """Struktura danych Trie (drzewo prefiksowe) z obsługą autouzupełniania
    i rankingiem wyników na podstawie częstości występowania słów.
    """

    def __init__(self) -> None:
        self.root: TrieNode = TrieNode()

    def insert(self, word: str, frequency: int = 1) -> None:
        if frequency <= 0:
            raise ValueError("Częstotliwość musi być liczbą dodatnią (większą od zera).")

        current = self.root
        for char in word:
            if char not in current.children:
                current.children[char] = TrieNode()
            current = current.children[char]

        current.is_end_of_word = True
        current.frequency += frequency

    def search(self, word: str) -> bool:
        node = self._find_node(word)
        return node is not None and node.is_end_of_word

    def get_frequency(self, word: str) -> int:
        node = self._find_node(word)
        if node and node.is_end_of_word:
            return node.frequency
        return 0

    def autocomplete(
        self, prefix: str, limit: Optional[int] = None
    ) -> list[tuple[str, int]]:
        start_node = self._find_node(prefix)
        if not start_node:
            return []

        results: list[tuple[str, int]] = []
        self._dfs_collect(start_node, list(prefix), results)

        results.sort(key=lambda item: (-item[1], item[0]))
        return results[:limit] if limit is not None else results

    def _find_node(self, prefix: str) -> Optional[TrieNode]:
        current = self.root
        for char in prefix:
            if char not in current.children:
                return None
            current = current.children[char]
        return current

    def _dfs_collect(
        self, node: TrieNode, current_path: list[str], results: list[tuple[str, int]]
    ) -> None:
        if node.is_end_of_word:
            results.append(("".join(current_path), node.frequency))

        for char, child_node in node.children.items():
            current_path.append(char)
            self._dfs_collect(child_node, current_path, results)
            current_path.pop()


class TestAutocompleteTrie(unittest.TestCase):
    def setUp(self) -> None:
        self.trie = AutocompleteTrie()

    def test_insert_search_and_frequency_accumulation(self) -> None:
        self.trie.insert("python", frequency=10)
        self.trie.insert("python", frequency=5)
        self.trie.insert("py", frequency=2)

        self.assertTrue(self.trie.search("python"))
        self.assertTrue(self.trie.search("py"))
        self.assertFalse(self.trie.search("pyt"))
        self.assertFalse(self.trie.search("java"))

        self.assertEqual(self.trie.get_frequency("python"), 15)
        self.assertEqual(self.trie.get_frequency("py"), 2)
        self.assertEqual(self.trie.get_frequency("pyt"), 0)

    def test_autocomplete_ranking_and_limit(self) -> None:
        data = [
            ("program", 10),
            ("programowanie", 50),
            ("programista", 30),
            ("projekt", 40),
            ("produkt", 5),
        ]
        for word, freq in data:
            self.trie.insert(word, freq)

        suggestions = self.trie.autocomplete("prog")
        expected = [
            ("programowanie", 50),
            ("programista", 30),
            ("program", 10),
        ]
        self.assertEqual(suggestions, expected)

        limited_suggestions = self.trie.autocomplete("prog", limit=2)
        self.assertEqual(limited_suggestions, expected[:2])

    def test_edge_cases_empty_prefix_missing_word_and_invalid_input(self) -> None:
        self.trie.insert("kot", 3)
        self.trie.insert("pies", 8)

        all_words = self.trie.autocomplete("")
        self.assertEqual(all_words, [("pies", 8), ("kot", 3)])

        self.assertEqual(self.trie.autocomplete("xyz"), [])

        with self.assertRaises(ValueError):
            self.trie.insert("błąd", frequency=0)

        with self.assertRaises(ValueError):
            self.trie.insert("błąd", frequency=-5)


if __name__ == "__main__":
    unittest.main()
