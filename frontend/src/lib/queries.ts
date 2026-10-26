import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type ChatMessage,
  type ChatSession,
  type Course,
  type DocumentRow,
  type Member,
  type MemberRole,
  type User,
} from "./api/client";

export const keys = {
  me: ["me"] as const,
  courses: ["courses"] as const,
  course: (id: string) => ["courses", id] as const,
  documents: (courseId: string) => ["courses", courseId, "documents"] as const,
  members: (courseId: string) => ["courses", courseId, "members"] as const,
  sessions: (courseId: string) => ["courses", courseId, "sessions"] as const,
  messages: (sessionId: string) => ["sessions", sessionId, "messages"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api.get<User>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useCourses() {
  return useQuery({ queryKey: keys.courses, queryFn: () => api.get<Course[]>("/api/courses") });
}

export function useCourse(courseId: string) {
  return useQuery({
    queryKey: keys.course(courseId),
    queryFn: () => api.get<Course>(`/api/courses/${courseId}`),
  });
}

const IN_PROGRESS = new Set(["uploaded", "extracting", "chunking", "embedding"]);

export function useDocuments(courseId: string) {
  return useQuery({
    queryKey: keys.documents(courseId),
    queryFn: () => api.get<DocumentRow[]>(`/api/courses/${courseId}/documents`),
    // Poll while anything is still being indexed.
    refetchInterval: (q) => (q.state.data?.some((d) => IN_PROGRESS.has(d.status)) ? 1500 : false),
  });
}

export function useMembers(courseId: string) {
  return useQuery({
    queryKey: keys.members(courseId),
    queryFn: () => api.get<Member[]>(`/api/courses/${courseId}/members`),
  });
}

export function useSessions(courseId: string, q?: string) {
  return useQuery({
    queryKey: [...keys.sessions(courseId), q ?? ""],
    queryFn: () =>
      api.get<ChatSession[]>(
        `/api/courses/${courseId}/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`,
      ),
  });
}

export function useMessages(sessionId: string | undefined) {
  return useQuery({
    queryKey: keys.messages(sessionId ?? "none"),
    queryFn: () => api.get<ChatMessage[]>(`/api/sessions/${sessionId}/messages`),
    enabled: Boolean(sessionId),
  });
}

export function useCreateCourse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.post<Course>("/api/courses", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.courses }),
  });
}

export function useUpdateCourse(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name?: string; description?: string | null }) =>
      api.patch<Course>(`/api/courses/${courseId}`, data),
    onSuccess: (course) => {
      qc.setQueryData(keys.course(courseId), course);
      qc.invalidateQueries({ queryKey: keys.courses });
    },
  });
}

export function useDeleteCourse(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del(`/api/courses/${courseId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.courses }),
  });
}

export function useAddMember(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { email: string; role: MemberRole }) =>
      api.post<Member>(`/api/courses/${courseId}/members`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(courseId) }),
  });
}

export function useRemoveMember(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => api.del(`/api/courses/${courseId}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(courseId) }),
  });
}

export function useDeleteDocument(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => api.del(`/api/courses/${courseId}/documents/${docId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.documents(courseId) });
      qc.invalidateQueries({ queryKey: keys.course(courseId) });
    },
  });
}

export function useReprocessDocument(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) =>
      api.post<DocumentRow>(`/api/courses/${courseId}/documents/${docId}/reprocess`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents(courseId) }),
  });
}

export function useRenameSession(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch<ChatSession>(`/api/sessions/${id}`, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sessions(courseId) }),
  });
}

export function useDeleteSession(courseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sessions(courseId) }),
  });
}
