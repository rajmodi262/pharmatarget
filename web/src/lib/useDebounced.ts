import { useEffect, useState } from "react";

/**
 * Debounce a rapidly-changing value.
 *
 * Applied to the search box: firing a query per keystroke would put a dozen
 * requests in flight for "PATEL" and render whichever returned last, which is
 * not necessarily the one the user is still typing.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);

  return debounced;
}
