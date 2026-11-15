"""Write data/problems.json from the problem definitions below.

The bank is authored here as Python so the reference solutions and multi-line code stay readable.
Run: python scripts/build_problems.py   then   python scripts/validate_bank.py

Each problem:
  visible_tests   shown to the student (name, input text, expected)
  hidden_tests   never leave the server (call expression, expected expression)
  reference_solution   never leaves the server
  hint_seeds   levels 1 to 5; level 5 is a pseudocode skeleton of at most 12 lines
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "problems.json"


def vt(name: str, display: str, call: str, expected: str, normalize: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "input": display, "call": call, "expected": expected}
    if normalize:
        item["normalize"] = normalize
    return item


def ht(name: str, call: str, expected: str, normalize: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "call": call, "expected": expected}
    if normalize:
        item["normalize"] = normalize
    return item


PROBLEMS: list[dict[str, Any]] = [
    {
        "id": "two-sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "pattern": "hash map",
        "statement": (
            "Given a list of integers `nums` and an integer `target`, return the indices of the two "
            "numbers that add up to `target`. Exactly one solution exists and you may not use the same "
            "element twice. Any order is fine."
        ),
        "starter_code": "def two_sum(nums: list[int], target: int) -> list[int]:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(n) space",
        "reference_solution": (
            "def two_sum(nums, target):\n"
            "    seen = {}\n"
            "    for i, n in enumerate(nums):\n"
            "        if target - n in seen:\n"
            "            return [seen[target - n], i]\n"
            "        seen[n] = i\n"
            "    return []\n"
        ),
        "visible_tests": [
            vt("example 1", "nums=[2,7,11,15], target=9", "two_sum([2,7,11,15], 9)", "[0, 1]", "sorted"),
            vt("example 2", "nums=[3,2,4], target=6", "two_sum([3,2,4], 6)", "[1, 2]", "sorted"),
            vt("duplicates", "nums=[3,3], target=6", "two_sum([3,3], 6)", "[0, 1]", "sorted"),
        ],
        "hidden_tests": [
            ht("negatives and zero", "two_sum([-3,4,3,90], 0)", "[0, 2]", "sorted"),
            ht("pair at the ends", "two_sum([1,2,3,4,5], 6)", "[1, 3]", "sorted"),
            ht("zeros", "two_sum([0,4,3,0], 0)", "[0, 3]", "sorted"),
            ht("large", "two_sum(list(range(1, 10001)), 19999)", "[9998, 9999]", "sorted"),
        ],
        "hint_seeds": {
            "1": "Restate the task: find two positions whose values sum to the target. What must be true about the pair?",
            "2": "This is a hash map problem. Think about trading memory for speed when you look for a partner value.",
            "3": "As you scan each number, what could you remember so you can recognise its partner later?",
            "4": "For each value n, the partner must equal target minus n. Remember the values you have already seen with their indices, and look up the complement each time.",
            "5": "def two_sum(nums, target):\n    seen = {}  # value -> index\n    for i, n in enumerate(nums):\n        # is target - n already in seen?\n        #   yes: return the stored index and i\n        # record n -> i\n    # no pair found\n",
        },
    },
    {
        "id": "valid-parentheses",
        "title": "Valid Parentheses",
        "difficulty": "easy",
        "pattern": "stack",
        "statement": (
            "Given a string `s` containing only the characters `()[]{}`, return True if the brackets are "
            "valid: every opening bracket is closed by a bracket of the same type, in the correct order."
        ),
        "starter_code": "def is_valid(s: str) -> bool:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(n) space",
        "reference_solution": (
            "def is_valid(s):\n"
            "    pairs = {')': '(', ']': '[', '}': '{'}\n"
            "    stack = []\n"
            "    for ch in s:\n"
            "        if ch in pairs:\n"
            "            if not stack or stack[-1] != pairs[ch]:\n"
            "                return False\n"
            "            stack.pop()\n"
            "        else:\n"
            "            stack.append(ch)\n"
            "    return not stack\n"
        ),
        "visible_tests": [
            vt("simple pair", 's="()"', 'is_valid("()")', "True"),
            vt("mixed", 's="()[]{}"', 'is_valid("()[]{}")', "True"),
            vt("wrong order", 's="(]"', 'is_valid("(]")', "False"),
        ],
        "hidden_tests": [
            ht("empty string", 'is_valid("")', "True"),
            ht("nested ok", 'is_valid("{[]}")', "True"),
            ht("interleaved", 'is_valid("([)]")', "False"),
            ht("unclosed", 'is_valid("((")', "False"),
            ht("lone closer", 'is_valid("]")', "False"),
        ],
        "hint_seeds": {
            "1": "Clarify the rule: every opening bracket must be closed by the matching kind, and the nesting order must be right.",
            "2": "This is a stack problem. Which data structure gives you the most recent unmatched opener?",
            "3": "When you meet a closing bracket, what should you check about the most recent unmatched opener?",
            "4": "Push each opener. On a closer, the top of the stack must be its matching opener, otherwise the answer is False. At the end the stack must be empty.",
            "5": "def is_valid(s):\n    pairs = {closer: opener}\n    stack = []\n    for ch in s:\n        # if ch is a closer: check the stack top, then pop\n        # otherwise push ch\n    # return whether the stack is empty\n",
        },
    },
    {
        "id": "best-time-to-sell",
        "title": "Best Time to Buy and Sell Stock",
        "difficulty": "easy",
        "pattern": "sliding window",
        "statement": (
            "Given `prices`, where prices[i] is the price of a stock on day i, return the maximum profit from "
            "one buy followed by one later sell. Return 0 if no profit is possible."
        ),
        "starter_code": "def max_profit(prices: list[int]) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(1) space",
        "reference_solution": (
            "def max_profit(prices):\n"
            "    best = 0\n"
            "    low = float('inf')\n"
            "    for p in prices:\n"
            "        low = min(low, p)\n"
            "        best = max(best, p - low)\n"
            "    return best\n"
        ),
        "visible_tests": [
            vt("example 1", "prices=[7,1,5,3,6,4]", "max_profit([7,1,5,3,6,4])", "5"),
            vt("falling", "prices=[7,6,4,3,1]", "max_profit([7,6,4,3,1])", "0"),
        ],
        "hidden_tests": [
            ht("empty", "max_profit([])", "0"),
            ht("dip then rise", "max_profit([2,4,1])", "2"),
            ht("two days", "max_profit([1,2])", "1"),
            ht("flat", "max_profit([3,3,3])", "0"),
            ht("multiple dips", "max_profit([2,1,2,1,0,1,2])", "2"),
        ],
        "hint_seeds": {
            "1": "You may buy once and sell once later. What is the profit you are maximising?",
            "2": "Think of a window of days: the buy day is the lowest price seen so far.",
            "3": "While scanning left to right, what do you need to remember at each day to compute the best sale right now?",
            "4": "Track the lowest price so far. For each day, the candidate profit is today's price minus that lowest price. Keep the best candidate.",
            "5": "def max_profit(prices):\n    best = 0\n    low = <lowest so far>\n    for p in prices:\n        # update low\n        # update best with p - low\n    return best\n",
        },
    },
    {
        "id": "longest-unique-substring",
        "title": "Longest Substring Without Repeating Characters",
        "difficulty": "medium",
        "pattern": "sliding window",
        "statement": (
            "Given a string `s`, return the length of the longest substring that has no repeated characters."
        ),
        "starter_code": "def length_of_longest_substring(s: str) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(min(n, alphabet)) space",
        "reference_solution": (
            "def length_of_longest_substring(s):\n"
            "    last = {}\n"
            "    left = 0\n"
            "    best = 0\n"
            "    for right, ch in enumerate(s):\n"
            "        if ch in last and last[ch] >= left:\n"
            "            left = last[ch] + 1\n"
            "        last[ch] = right\n"
            "        best = max(best, right - left + 1)\n"
            "    return best\n"
        ),
        "visible_tests": [
            vt("example 1", 's="abcabcbb"', 'length_of_longest_substring("abcabcbb")', "3"),
            vt("all same", 's="bbbbb"', 'length_of_longest_substring("bbbbb")', "1"),
            vt("subsequence trap", 's="pwwkew"', 'length_of_longest_substring("pwwkew")', "3"),
        ],
        "hidden_tests": [
            ht("empty", 'length_of_longest_substring("")', "0"),
            ht("repeat after gap", 'length_of_longest_substring("abba")', "2"),
            ht("single space", 'length_of_longest_substring(" ")', "1"),
            ht("mid window", 'length_of_longest_substring("dvdf")', "3"),
            ht("long", 'length_of_longest_substring("tmmzuxt")', "5"),
        ],
        "hint_seeds": {
            "1": "You need the longest run of characters that never repeats. What makes a window invalid?",
            "2": "This is a sliding window: keep a left and right edge, and move the left edge only when you must.",
            "3": "When the right character is already inside the window, where should the left edge jump to?",
            "4": "Remember the last index of each character. When a character repeats inside the current window, move the left edge just past its previous index. Track the widest window.",
            "5": "def length_of_longest_substring(s):\n    last = {}  # char -> last index\n    left = 0\n    best = 0\n    for right, ch in enumerate(s):\n        # if ch was seen at or after left: move left past it\n        # record ch -> right\n        # update best with the window size\n    return best\n",
        },
    },
    {
        "id": "two-sum-sorted",
        "title": "Two Sum II (Sorted Input)",
        "difficulty": "easy",
        "pattern": "two pointers",
        "statement": (
            "Given a list `numbers` sorted in non-decreasing order and a `target`, return the 1-based indices "
            "[i, j] (i < j) of the two numbers that add up to `target`. Exactly one solution exists."
        ),
        "starter_code": "def two_sum_sorted(numbers: list[int], target: int) -> list[int]:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(1) space",
        "reference_solution": (
            "def two_sum_sorted(numbers, target):\n"
            "    lo, hi = 0, len(numbers) - 1\n"
            "    while lo < hi:\n"
            "        s = numbers[lo] + numbers[hi]\n"
            "        if s == target:\n"
            "            return [lo + 1, hi + 1]\n"
            "        if s < target:\n"
            "            lo += 1\n"
            "        else:\n"
            "            hi -= 1\n"
            "    return []\n"
        ),
        "visible_tests": [
            vt("example 1", "numbers=[2,7,11,15], target=9", "two_sum_sorted([2,7,11,15], 9)", "[1, 2]"),
            vt("example 2", "numbers=[2,3,4], target=6", "two_sum_sorted([2,3,4], 6)", "[1, 3]"),
            vt("negatives", "numbers=[-1,0], target=-1", "two_sum_sorted([-1,0], -1)", "[1, 2]"),
        ],
        "hidden_tests": [
            ht("duplicates", "two_sum_sorted([1,2,3,4,4,9,56,90], 8)", "[4, 5]"),
            ht("zeros", "two_sum_sorted([0,0,3,4], 0)", "[1, 2]"),
            ht("ends", "two_sum_sorted([1,3,5], 6)", "[1, 3]"),
        ],
        "hint_seeds": {
            "1": "The list is sorted. What does moving one end inward do to the sum?",
            "2": "This is a two pointers problem: one pointer at each end of the list.",
            "3": "If the sum is too small, which pointer should move? Which pointer if it is too big?",
            "4": "Start at both ends. If the sum equals the target, return the 1-based positions. If the sum is smaller, move the left pointer right; if larger, move the right pointer left.",
            "5": "def two_sum_sorted(numbers, target):\n    lo, hi = 0, len(numbers) - 1\n    while lo < hi:\n        s = numbers[lo] + numbers[hi]\n        # equal: return 1-based positions\n        # too small: move lo\n        # too big: move hi\n    return []\n",
        },
    },
    {
        "id": "container-most-water",
        "title": "Container With Most Water",
        "difficulty": "medium",
        "pattern": "two pointers",
        "statement": (
            "Given `height`, where height[i] is the height of a vertical line at position i, pick two lines that "
            "together with the x-axis hold the most water. Return the maximum area."
        ),
        "starter_code": "def max_area(height: list[int]) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n) time, O(1) space",
        "reference_solution": (
            "def max_area(height):\n"
            "    lo, hi = 0, len(height) - 1\n"
            "    best = 0\n"
            "    while lo < hi:\n"
            "        best = max(best, (hi - lo) * min(height[lo], height[hi]))\n"
            "        if height[lo] < height[hi]:\n"
            "            lo += 1\n"
            "        else:\n"
            "            hi -= 1\n"
            "    return best\n"
        ),
        "visible_tests": [
            vt("example 1", "height=[1,8,6,2,5,4,8,3,7]", "max_area([1,8,6,2,5,4,8,3,7])", "49"),
            vt("two lines", "height=[1,1]", "max_area([1,1])", "1"),
        ],
        "hidden_tests": [
            ht("empty", "max_area([])", "0"),
            ht("outer walls", "max_area([4,3,2,1,4])", "16"),
            ht("narrow", "max_area([1,2,1])", "2"),
            ht("zeros", "max_area([0,0])", "0"),
            ht("late peak", "max_area([2,3,4,5,18,17,6])", "17"),
        ],
        "hint_seeds": {
            "1": "The area is width times the shorter line. Which lines are worth comparing?",
            "2": "Start with the widest pair, the two ends. What can you give up when you move one end?",
            "3": "The shorter line limits the area. If you move the taller line inward, can the area get bigger?",
            "4": "Use two pointers at the ends. Record the area, then move the pointer on the shorter line inward, since that line limits the area.",
            "5": "def max_area(height):\n    lo, hi = 0, len(height) - 1\n    best = 0\n    while lo < hi:\n        # best = max(best, width * min(height[lo], height[hi]))\n        # move the pointer on the shorter line\n    return best\n",
        },
    },
    {
        "id": "binary-search",
        "title": "Binary Search",
        "difficulty": "easy",
        "pattern": "binary search",
        "statement": (
            "Given a sorted list `nums` of distinct integers and a `target`, return its index, or -1 if it is not present."
        ),
        "starter_code": "def search(nums: list[int], target: int) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(log n) time, O(1) space",
        "reference_solution": (
            "def search(nums, target):\n"
            "    lo, hi = 0, len(nums) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if nums[mid] == target:\n"
            "            return mid\n"
            "        if nums[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"
        ),
        "visible_tests": [
            vt("found", "nums=[-1,0,3,5,9,12], target=9", "search([-1,0,3,5,9,12], 9)", "4"),
            vt("missing", "nums=[-1,0,3,5,9,12], target=2", "search([-1,0,3,5,9,12], 2)", "-1"),
        ],
        "hidden_tests": [
            ht("single found", "search([5], 5)", "0"),
            ht("single missing", "search([5], -5)", "-1"),
            ht("empty", "search([], 1)", "-1"),
            ht("first", "search([1,3,5,7,9], 1)", "0"),
            ht("last", "search([1,3,5,7,9], 9)", "4"),
        ],
        "hint_seeds": {
            "1": "The list is sorted. Where could the target be if you check one element?",
            "2": "This is a binary search problem: halve the search range each step.",
            "3": "Compare the middle element with the target. Which half can you throw away?",
            "4": "Keep a low and high bound. Check the middle: if it matches, return it. If it is smaller than the target, search the right half; otherwise the left half. Stop when the bounds cross.",
            "5": "def search(nums, target):\n    lo, hi = 0, len(nums) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        # found: return mid\n        # middle too small: move lo\n        # middle too big: move hi\n    return -1\n",
        },
    },
    {
        "id": "find-minimum-rotated",
        "title": "Find Minimum in Rotated Sorted Array",
        "difficulty": "medium",
        "pattern": "binary search",
        "statement": (
            "A sorted array of distinct integers was rotated between 1 and n times. Return the minimum element. "
            "Your solution must run in O(log n) time."
        ),
        "starter_code": "def find_min(nums: list[int]) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(log n) time, O(1) space",
        "reference_solution": (
            "def find_min(nums):\n"
            "    lo, hi = 0, len(nums) - 1\n"
            "    while lo < hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if nums[mid] > nums[hi]:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid\n"
            "    return nums[lo]\n"
        ),
        "visible_tests": [
            vt("rotated", "nums=[3,4,5,1,2]", "find_min([3,4,5,1,2])", "1"),
            vt("bigger rotation", "nums=[4,5,6,7,0,1,2]", "find_min([4,5,6,7,0,1,2])", "0"),
            vt("not rotated", "nums=[11,13,15,17]", "find_min([11,13,15,17])", "11"),
        ],
        "hidden_tests": [
            ht("two items", "find_min([2,1])", "1"),
            ht("no rotation", "find_min([1,2,3,4,5])", "1"),
            ht("rotated late", "find_min([6,7,1,2,3,4,5])", "1"),
            ht("single", "find_min([9])", "9"),
            ht("tiny rotated", "find_min([3,1,2])", "1"),
        ],
        "hint_seeds": {
            "1": "The minimum is where the sorted order breaks. What does the middle element tell you about which side holds the break?",
            "2": "This is still binary search, but the comparison is against the right end, not the target.",
            "3": "If the middle is larger than the right end, the minimum is to the right of the middle. Otherwise it is at the middle or to the left.",
            "4": "Compare the middle with the right end. If the middle is bigger, move the low bound past it. Otherwise move the high bound onto the middle. Stop when the bounds meet.",
            "5": "def find_min(nums):\n    lo, hi = 0, len(nums) - 1\n    while lo < hi:\n        mid = (lo + hi) // 2\n        # if nums[mid] > nums[hi]: the minimum is right of mid\n        # else: the minimum is at mid or left of it\n    return nums[lo]\n",
        },
    },
    {
        "id": "merge-intervals",
        "title": "Merge Intervals",
        "difficulty": "medium",
        "pattern": "intervals",
        "statement": (
            "Given a list of intervals `[start, end]`, merge all overlapping intervals and return the merged "
            "intervals sorted by start."
        ),
        "starter_code": "def merge(intervals: list[list[int]]) -> list[list[int]]:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n log n) time, O(n) space",
        "reference_solution": (
            "def merge(intervals):\n"
            "    out = []\n"
            "    for start, end in sorted(intervals):\n"
            "        if out and start <= out[-1][1]:\n"
            "            out[-1][1] = max(out[-1][1], end)\n"
            "        else:\n"
            "            out.append([start, end])\n"
            "    return out\n"
        ),
        "visible_tests": [
            vt("example 1", "intervals=[[1,3],[2,6],[8,10],[15,18]]", "merge([[1,3],[2,6],[8,10],[15,18]])", "[[1, 6], [8, 10], [15, 18]]"),
            vt("touching", "intervals=[[1,4],[4,5]]", "merge([[1,4],[4,5]])", "[[1, 5]]"),
        ],
        "hidden_tests": [
            ht("empty", "merge([])", "[]"),
            ht("unsorted input", "merge([[1,4],[0,0]])", "[[0, 0], [1, 4]]"),
            ht("contained", "merge([[1,4],[2,3]])", "[[1, 4]]"),
            ht("chain", "merge([[1,4],[0,2],[3,5]])", "[[0, 5]]"),
            ht("disjoint", "merge([[1,2],[3,4]])", "[[1, 2], [3, 4]]"),
        ],
        "hint_seeds": {
            "1": "Two intervals overlap when one starts before the other ends. What order would make overlaps easy to spot?",
            "2": "Sorting by start makes this a single pass problem.",
            "3": "After sorting, compare each interval with the last merged one. When do you extend it, and when do you start a new one?",
            "4": "Sort by start. Walk the list: if the current start is at or before the end of the last merged interval, extend that end to the larger of the two ends. Otherwise start a new interval.",
            "5": "def merge(intervals):\n    out = []\n    for start, end in <sorted by start>:\n        # if it overlaps out[-1]: extend that end\n        # else: append [start, end]\n    return out\n",
        },
    },
    {
        "id": "number-of-islands",
        "title": "Number of Islands",
        "difficulty": "medium",
        "pattern": "BFS/DFS",
        "statement": (
            "Given a 2D grid of '1' (land) and '0' (water), count the islands. An island is a group of land cells "
            "connected horizontally or vertically."
        ),
        "starter_code": "def num_islands(grid: list[list[str]]) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(rows * cols) time and space",
        "reference_solution": (
            "from collections import deque\n"
            "\n"
            "def num_islands(grid):\n"
            "    if not grid:\n"
            "        return 0\n"
            "    rows, cols = len(grid), len(grid[0])\n"
            "    seen = [[False] * cols for _ in range(rows)]\n"
            "    count = 0\n"
            "    for r in range(rows):\n"
            "        for c in range(cols):\n"
            "            if grid[r][c] == '1' and not seen[r][c]:\n"
            "                count += 1\n"
            "                seen[r][c] = True\n"
            "                q = deque([(r, c)])\n"
            "                while q:\n"
            "                    y, x = q.popleft()\n"
            "                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):\n"
            "                        ny, nx = y + dy, x + dx\n"
            "                        if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] == '1' and not seen[ny][nx]:\n"
            "                            seen[ny][nx] = True\n"
            "                            q.append((ny, nx))\n"
            "    return count\n"
        ),
        "visible_tests": [
            vt(
                "one island",
                "grid: a 4x5 map with one large island",
                "num_islands([['1','1','1','1','0'],['1','1','0','1','0'],['1','1','0','0','0'],['0','0','0','0','0']])",
                "1",
            ),
            vt(
                "three islands",
                "grid: a 4x5 map with three islands",
                "num_islands([['1','1','0','0','0'],['1','1','0','0','0'],['0','0','1','0','0'],['0','0','0','1','1']])",
                "3",
            ),
        ],
        "hidden_tests": [
            ht("empty grid", "num_islands([])", "0"),
            ht("single water", "num_islands([['0']])", "0"),
            ht("single land", "num_islands([['1']])", "1"),
            ht("checkerboard", "num_islands([['1','0','1'],['0','1','0'],['1','0','1']])", "5"),
            ht("one row", "num_islands([['1','1','1']])", "1"),
        ],
        "hint_seeds": {
            "1": "What is one island, in terms of the cells? How do you know two land cells belong to the same one?",
            "2": "This is a graph traversal problem: each land cell is a node and neighbours are up, down, left and right.",
            "3": "Scan the grid. Each time you find land you have not visited, you have found a new island. What should you do with the rest of that island?",
            "4": "Scan every cell. When you find unvisited land, count a new island and flood-fill everything reachable from it using BFS or DFS, marking cells as visited.",
            "5": "def num_islands(grid):\n    seen = <visited grid>\n    count = 0\n    for each cell (r, c):\n        if land and not seen:\n            count += 1\n            # traverse all connected land from (r, c), marking seen\n    return count\n",
        },
    },
    {
        "id": "coin-change",
        "title": "Coin Change",
        "difficulty": "medium",
        "pattern": "dynamic programming",
        "statement": (
            "Given coin denominations `coins` and a total `amount`, return the fewest coins needed to make the amount, "
            "or -1 if it cannot be made. You have an unlimited supply of each coin."
        ),
        "starter_code": "def coin_change(coins: list[int], amount: int) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(amount * len(coins)) time, O(amount) space",
        "reference_solution": (
            "def coin_change(coins, amount):\n"
            "    INF = amount + 1\n"
            "    dp = [0] + [INF] * amount\n"
            "    for a in range(1, amount + 1):\n"
            "        for c in coins:\n"
            "            if c <= a and dp[a - c] + 1 < dp[a]:\n"
            "                dp[a] = dp[a - c] + 1\n"
            "    return dp[amount] if dp[amount] != INF else -1\n"
        ),
        "visible_tests": [
            vt("example 1", "coins=[1,2,5], amount=11", "coin_change([1,2,5], 11)", "3"),
            vt("impossible", "coins=[2], amount=3", "coin_change([2], 3)", "-1"),
            vt("zero", "coins=[1], amount=0", "coin_change([1], 0)", "0"),
        ],
        "hidden_tests": [
            ht("ones", "coin_change([1], 2)", "2"),
            ht("large", "coin_change([186,419,83,408], 6249)", "20"),
            ht("zero with coins", "coin_change([3,7], 0)", "0"),
            ht("greedy trap", "coin_change([2,5,10,1], 27)", "4"),
        ],
        "hint_seeds": {
            "1": "You want the fewest coins. If you knew the fewest coins for every smaller amount, could you build up to the target?",
            "2": "This is dynamic programming. Build a table where entry a is the fewest coins for amount a.",
            "3": "For amount a, the last coin you add is some denomination c. What smaller amount do you need to solve first?",
            "4": "Fill the table from 0 up to the amount. For each amount, try every coin that fits and take the best result from amount minus that coin, plus one. Mark unreachable amounts with a value larger than any real answer.",
            "5": "def coin_change(coins, amount):\n    dp = [0] + [<unreachable>] * amount\n    for a in range(1, amount + 1):\n        for c in coins:\n            # if c fits: dp[a] = min(dp[a], dp[a - c] + 1)\n    # return dp[amount], or -1 if unreachable\n",
        },
    },
    {
        "id": "kth-largest",
        "title": "Kth Largest Element in an Array",
        "difficulty": "medium",
        "pattern": "heap",
        "statement": (
            "Given an integer list `nums` and an integer `k`, return the k-th largest element in the list. "
            "Count duplicates as separate elements."
        ),
        "starter_code": "def find_kth_largest(nums: list[int], k: int) -> int:\n    # your code here\n    pass\n",
        "expected_complexity": "O(n log k) time, O(k) space",
        "reference_solution": (
            "import heapq\n"
            "\n"
            "def find_kth_largest(nums, k):\n"
            "    heap = []\n"
            "    for n in nums:\n"
            "        heapq.heappush(heap, n)\n"
            "        if len(heap) > k:\n"
            "            heapq.heappop(heap)\n"
            "    return heap[0]\n"
        ),
        "visible_tests": [
            vt("example 1", "nums=[3,2,1,5,6,4], k=2", "find_kth_largest([3,2,1,5,6,4], 2)", "5"),
            vt("duplicates", "nums=[3,2,3,1,2,4,5,5,6], k=4", "find_kth_largest([3,2,3,1,2,4,5,5,6], 4)", "4"),
        ],
        "hidden_tests": [
            ht("single", "find_kth_largest([1], 1)", "1"),
            ht("all equal", "find_kth_largest([7,7,7], 2)", "7"),
            ht("negatives", "find_kth_largest([-1,-2,-3], 1)", "-1"),
            ht("duplicate counted", "find_kth_largest([5,1,9,3,9], 3)", "5"),
            ht("k equals length", "find_kth_largest([10,20,30,40,50], 5)", "10"),
        ],
        "hint_seeds": {
            "1": "Sorting works, but can you find the answer without sorting everything?",
            "2": "This is a heap problem. A min-heap of size k keeps only the k largest values seen so far.",
            "3": "If the heap holds more than k items, which one can you discard? What is left at the top?",
            "4": "Push each number onto a min-heap. Whenever the heap grows past k, pop the smallest. At the end the heap top is the k-th largest.",
            "5": "import heapq\n\ndef find_kth_largest(nums, k):\n    heap = []\n    for n in nums:\n        # push n\n        # if the heap is larger than k: pop\n    return heap[0]\n",
        },
    },
]


def build() -> list[dict[str, Any]]:
    return PROBLEMS


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(PROBLEMS)} problems to {OUT}")


if __name__ == "__main__":
    main()
