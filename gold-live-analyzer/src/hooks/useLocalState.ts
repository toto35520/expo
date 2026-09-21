'use client';

import { useCallback, useEffect, useState } from 'react';

/** useState persiste dans localStorage, tolerant aux navigations privees. */
export function useLocalState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(initial);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) setValue({ ...initial, ...(JSON.parse(raw) as T) });
    } catch {
      // stockage indisponible : on reste sur la valeur par defaut
    }
    // La cle seule pilote la relecture : `initial` est une valeur de depart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // ecriture impossible : la valeur reste en memoire pour la session
      }
    },
    [key]
  );

  return [value, update];
}
