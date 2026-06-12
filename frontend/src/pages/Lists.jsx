/**
 * ============================================================================
 * Project:  River Vortex — Smart Home Hub for the River Song AI Ecosystem
 * File:     frontend/src/pages/Lists.jsx
 * Purpose:  Shopping/to-do list display — checklist UI for the lists
 *           snapshot River Song pushes via POST /api/vortex/v1/lists
 *           (core/lists.py, core/lists_api.py). Tapping an item toggles its
 *           checked state via POST /api/vortex/v1/lists/{list_id}/items/
 *           {item_id}/toggle; the update is broadcast back to every
 *           connected display over /api/ws (`lists_update`).
 * Author:   [Author Placeholder]
 * Version:  1.0.0
 * Date:     2026-06-12
 * License:  Internal Use Only — River Song AI / riversongai.com
 * ============================================================================
 */

import React, { useCallback } from 'react';
import NotificationBar from '../components/NotificationBar';
import TimersWidget from '../components/TimersWidget';
import { useApp } from '../App';

const LISTS_BASE = '/api/vortex/v1/lists';

/**
 * Lists page — shopping/to-do lists with tap-to-toggle items.
 */
export default function Lists() {
  const { state, navigate } = useApp();
  const lists = state.lists || [];

  const toggleItem = useCallback((listId, itemId) => {
    fetch(`${LISTS_BASE}/${listId}/items/${itemId}/toggle`, { method: 'POST' }).catch(() => {});
  }, []);

  return (
    <div style={styles.container}>
      <NotificationBar />
      <TimersWidget />

      {/* Header */}
      <div style={styles.header}>
        <button
          style={styles.backBtn}
          onClick={() => navigate('dashboard')}
          aria-label="Back to dashboard"
        >
          ← Back
        </button>
        <span style={styles.title}>Lists</span>
        <span style={styles.count}>{lists.length} list{lists.length === 1 ? '' : 's'}</span>
      </div>

      {/* Content */}
      <div style={styles.content}>
        {lists.length === 0 ? (
          <div style={styles.empty}>
            <span style={styles.emptyIcon}>📝</span>
            <span style={styles.emptyText}>No lists yet</span>
          </div>
        ) : (
          lists.map((list) => {
            const items = list.items || [];
            const remaining = items.filter((i) => !i.checked).length;
            return (
              <div key={list.id} style={styles.listCard}>
                <div style={styles.listHeader}>
                  <span style={styles.listName}>{list.name}</span>
                  <span style={styles.listCount}>{remaining} left</span>
                </div>
                {items.length === 0 ? (
                  <div style={styles.listEmpty}>Nothing here yet</div>
                ) : (
                  items.map((item) => (
                    <button
                      key={item.id}
                      style={styles.item}
                      onClick={() => toggleItem(list.id, item.id)}
                      aria-pressed={!!item.checked}
                    >
                      <span style={{ ...styles.checkbox, ...(item.checked ? styles.checkboxChecked : {}) }}>
                        {item.checked ? '✓' : ''}
                      </span>
                      <span style={{ ...styles.itemText, ...(item.checked ? styles.itemTextChecked : {}) }}>
                        {item.text}
                      </span>
                    </button>
                  ))
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = {
  container: {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: '#0a0a0f',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '14px 20px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    flexShrink: 0,
  },
  backBtn: {
    background: 'none',
    border: 'none',
    color: '#7ab8ff',
    fontSize: 14,
    cursor: 'pointer',
    padding: '4px 0',
  },
  title: {
    flex: 1,
    fontSize: 16,
    fontWeight: 400,
    color: '#d0d0e8',
  },
  count: {
    fontSize: 12,
    color: '#555577',
  },
  content: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  listCard: {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 14,
    overflow: 'hidden',
  },
  listHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  },
  listName: {
    fontSize: 15,
    fontWeight: 500,
    color: '#d8d8f0',
  },
  listCount: {
    fontSize: 12,
    color: '#7070a0',
  },
  listEmpty: {
    padding: '16px',
    fontSize: 13,
    color: '#555577',
    textAlign: 'center',
  },
  item: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    background: 'none',
    border: 'none',
    borderBottom: '1px solid rgba(255,255,255,0.04)',
    padding: '14px 16px',
    cursor: 'pointer',
    textAlign: 'left',
  },
  checkbox: {
    flexShrink: 0,
    width: 22,
    height: 22,
    borderRadius: 6,
    border: '1px solid rgba(255,255,255,0.2)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 14,
    color: '#0a0a0f',
  },
  checkboxChecked: {
    background: '#4a9eff',
    border: '1px solid #4a9eff',
    color: '#0a0a0f',
  },
  itemText: {
    fontSize: 15,
    color: '#d0d0e8',
  },
  itemTextChecked: {
    color: '#555577',
    textDecoration: 'line-through',
  },
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    opacity: 0.6,
  },
  emptyIcon: {
    fontSize: 40,
  },
  emptyText: {
    fontSize: 16,
    color: '#8888aa',
  },
};
