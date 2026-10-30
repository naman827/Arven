import { describe, expect, it } from 'vitest'

import { initialJobState, jobReducer } from '@/features/research/useResearchJob'
import { parseBlock } from '@/lib/api'
import { dateGroup, linkCitations } from '@/lib/utils'

describe('linkCitations', () => {
  it('links single and grouped citations', () => {
    expect(linkCitations('A [1]. B [2, 3].')).toBe('A [1](#source-1). B [2](#source-2)[3](#source-3).')
  })
  it('leaves code and existing links alone', () => {
    const md = '`arr[1]` and [text](http://x) and\n```\nx[2]\n```'
    expect(linkCitations(md)).toBe(md)
  })
})

describe('parseBlock', () => {
  it('parses typed SSE events with ids', () => {
    expect(parseBlock('id: 7\nevent: token\ndata: {"text":"hi"}')).toEqual({ id: 7, type: 'token', data: { text: 'hi' } })
  })
  it('ignores comments and bad JSON', () => {
    expect(parseBlock(': ping')).toBeNull()
    expect(parseBlock('event: x\ndata: {bad')).toBeNull()
  })
})

describe('dateGroup', () => {
  const now = new Date(2026, 9, 29, 12)
  it('groups by recency', () => {
    expect(dateGroup(new Date(2026, 9, 29, 8).toISOString(), now)).toBe('Today')
    expect(dateGroup(new Date(2026, 9, 28, 8).toISOString(), now)).toBe('Yesterday')
    expect(dateGroup(new Date(2026, 9, 24).toISOString(), now)).toBe('Previous 7 days')
  })
})

describe('jobReducer', () => {
  it('tracks sources, draft resets, and completion', () => {
    let s = jobReducer(initialJobState, { type: 'status', data: { status: 'searching' } })
    s = jobReducer(s, { type: 'source_found', data: { number: 1, url: 'u', title: 't', domain: 'd' } })
    s = jobReducer(s, { type: 'source_read', data: { number: 1, readable: false, error: 'HTTP 403' } })
    expect(s.sources[1]).toMatchObject({ readable: false, error: 'HTTP 403' })
    s = jobReducer(s, { type: 'token', data: { text: 'partial' } })
    s = jobReducer(s, { type: 'reset', data: {} })
    expect(s.draft).toBe('')
    s = jobReducer(s, { type: 'done', data: { report_id: 'r1' } })
    expect(s).toMatchObject({ status: 'completed', reportId: 'r1' })
  })
  it('records failures', () => {
    expect(jobReducer(initialJobState, { type: 'error', data: { message: 'no search' } })).toMatchObject({ status: 'failed', error: 'no search' })
  })
})
