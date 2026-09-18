/**
 * Lightweight line-level unified diff using LCS (Longest Common Subsequence).
 * No external dependencies.
 */

export interface DiffLine {
  type: 'add' | 'remove' | 'context'
  content: string
  oldLineNo?: number
  newLineNo?: number
}

/**
 * Compute a unified diff between oldText and newText.
 * If oldText is null, the file is new and all lines are additions.
 */
export function computeUnifiedDiff(
  oldText: string | null,
  newText: string,
  _filename?: string,
): DiffLine[] {
  if (oldText === null) {
    // New file: all lines are additions.
    return newText.split('\n').map((line, i) => ({
      type: 'add' as const,
      content: line,
      newLineNo: i + 1,
    }))
  }

  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')

  // Build LCS table
  const m = oldLines.length
  const n = newLines.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // Backtrack to build diff
  const result: DiffLine[] = []
  let i = m
  let j = n

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.push({
        type: 'context',
        content: oldLines[i - 1],
        oldLineNo: i,
        newLineNo: j,
      })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.push({
        type: 'add',
        content: newLines[j - 1],
        newLineNo: j,
      })
      j--
    } else {
      result.push({
        type: 'remove',
        content: oldLines[i - 1],
        oldLineNo: i,
      })
      i--
    }
  }

  result.reverse()

  // Trim excessive context: show only 3 lines of context around changes.
  const CONTEXT_LINES = 3
  const hasChange = result.map(r => r.type !== 'context')
  const keep = new Array(result.length).fill(false)

  for (let idx = 0; idx < result.length; idx++) {
    if (hasChange[idx]) {
      for (let k = Math.max(0, idx - CONTEXT_LINES); k <= Math.min(result.length - 1, idx + CONTEXT_LINES); k++) {
        keep[k] = true
      }
    }
  }

  // If there are no changes at all, return empty.
  if (!hasChange.some(Boolean)) return []

  return result.filter((_, idx) => keep[idx])
}
