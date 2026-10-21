import localforage from "localforage";
import type { Session, Enrollment } from "./types";

const SESSIONS_KEY = "cached_sessions";
const ENROLLMENTS_KEY = "cached_enrollments";
const USER_KEY = "cached_user";

export async function cacheSessions(sessions: Session[]): Promise<void> {
  await localforage.setItem(SESSIONS_KEY, sessions);
}

export async function getCachedSessions(): Promise<Session[] | null> {
  return localforage.getItem<Session[]>(SESSIONS_KEY);
}

export async function cacheEnrollments(enrollments: Enrollment[]): Promise<void> {
  await localforage.setItem(ENROLLMENTS_KEY, enrollments);
}

export async function getCachedEnrollments(): Promise<Enrollment[] | null> {
  return localforage.getItem<Enrollment[]>(ENROLLMENTS_KEY);
}

export async function cacheUser(user: any): Promise<void> {
    await localforage.setItem(USER_KEY, user);
}

export async function getCachedUser(): Promise<any | null> {
    return localforage.getItem(USER_KEY);
}