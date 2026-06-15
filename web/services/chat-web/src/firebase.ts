import {initializeApp, type FirebaseApp} from "firebase/app";
import {getDatabase, onValue, ref, type Database} from "firebase/database";
import type {AgvTelemetry, ProcessSnapshot} from "./types";

// All config is injected at build time via VITE_FIREBASE_* env. When the database URL
// is absent we run in "disabled" mode and the dashboard falls back to the SSE/overlay
// path so the demo still renders without Firebase credentials.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  databaseURL: import.meta.env.VITE_FIREBASE_DATABASE_URL,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID
};

export const cellId = (import.meta.env.VITE_CELL_ID as string | undefined)?.trim() || "cell_demo";
export const firebaseEnabled = Boolean(firebaseConfig.databaseURL);

let app: FirebaseApp | null = null;
let database: Database | null = null;

if (firebaseEnabled) {
  try {
    app = initializeApp(firebaseConfig);
    database = getDatabase(app);
  } catch (error) {
    console.error("Firebase init failed; falling back to SSE telemetry.", error);
    database = null;
  }
}

type Unsubscribe = () => void;
const noop: Unsubscribe = () => undefined;

export function subscribeAgvs(onChange: (agvs: AgvTelemetry[]) => void): Unsubscribe {
  if (!database) return noop;
  const agvsRef = ref(database, `cells/${cellId}/agvs`);
  return onValue(agvsRef, (snapshot) => {
    const value = (snapshot.val() ?? {}) as Record<string, AgvTelemetry>;
    const agvs = Object.values(value).sort((a, b) => a.agv_id.localeCompare(b.agv_id));
    onChange(agvs);
  });
}

export function subscribeProcess(onChange: (process: ProcessSnapshot | null) => void): Unsubscribe {
  if (!database) return noop;
  const processRef = ref(database, `cells/${cellId}/process`);
  return onValue(processRef, (snapshot) => {
    onChange((snapshot.val() ?? null) as ProcessSnapshot | null);
  });
}
