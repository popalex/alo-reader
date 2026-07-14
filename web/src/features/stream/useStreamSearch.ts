// Search state for the entry list (WP-13, DESIGN.md §4.1), split out of EntryList.
// The raw box value is debounced into the term that drives the query; scope
// switches the active stream between this one and every subscription ("All").

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { StreamDescriptor } from "../../lib/streams";

export const ALL_STREAM: StreamDescriptor = { kind: "all" };

export function scopeLabel(stream: StreamDescriptor): string {
  switch (stream.kind) {
    case "feed":
      return "This feed";
    case "folder":
      return "This category";
    case "starred":
      return "Starred";
    case "all":
      return "All";
  }
}

export interface StreamSearch {
  searchInput: string;
  setSearchInput: (value: string) => void;
  searchTerm: string;
  scopeAll: boolean;
  setScopeAll: (value: boolean) => void;
  searching: boolean;
  clearSearch: () => void;
  /** The stream the list should actually query — the base stream, or All when a
   *  search is active and scoped to everything. */
  activeStream: StreamDescriptor;
  /** Focused by the `/` shortcut. */
  searchRef: RefObject<HTMLInputElement>;
}

export function useStreamSearch(stream: StreamDescriptor): StreamSearch {
  const searchRef = useRef<HTMLInputElement>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [scopeAll, setScopeAll] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setSearchTerm(searchInput.trim()), 200);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  const searching = searchTerm.length > 0;
  const clearSearch = useCallback(() => {
    setSearchInput("");
    setSearchTerm("");
  }, []);
  const activeStream = searching && scopeAll ? ALL_STREAM : stream;

  return {
    searchInput,
    setSearchInput,
    searchTerm,
    scopeAll,
    setScopeAll,
    searching,
    clearSearch,
    activeStream,
    searchRef,
  };
}
