// The entry list's search box: input + (for non-All streams) a scope toggle
// between this stream and All, + a clear button. State lives in useStreamSearch.

import { Search, X } from "lucide-react";

import type { StreamDescriptor } from "../../lib/streams";
import { scopeLabel, type StreamSearch } from "./useStreamSearch";
import styles from "./EntryList.module.css";

export function SearchBar({
  stream,
  title,
  search,
}: {
  stream: StreamDescriptor;
  title: string;
  search: StreamSearch;
}) {
  const { searchInput, setSearchInput, scopeAll, setScopeAll, clearSearch, searchRef } = search;
  return (
    <div className={styles.searchBar}>
      <Search size={14} className={styles.searchIcon} aria-hidden="true" />
      <input
        ref={searchRef}
        type="search"
        className={styles.searchInput}
        placeholder={`Search ${scopeAll ? "all articles" : title}`}
        aria-label="Search articles"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            clearSearch();
            e.currentTarget.blur();
          }
        }}
      />
      {searchInput ? (
        <>
          {stream.kind !== "all" ? (
            <div className={styles.scope} role="group" aria-label="Search scope">
              <button
                type="button"
                className={styles.scopeOpt}
                data-active={!scopeAll}
                aria-pressed={!scopeAll}
                onClick={() => setScopeAll(false)}
              >
                {scopeLabel(stream)}
              </button>
              <button
                type="button"
                className={styles.scopeOpt}
                data-active={scopeAll}
                aria-pressed={scopeAll}
                onClick={() => setScopeAll(true)}
              >
                All
              </button>
            </div>
          ) : null}
          <button
            type="button"
            className={styles.clear}
            aria-label="Clear search"
            title="Clear search (Esc)"
            onClick={clearSearch}
          >
            <X size={14} />
          </button>
        </>
      ) : null}
    </div>
  );
}
