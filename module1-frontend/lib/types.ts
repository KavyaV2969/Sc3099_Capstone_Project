export interface Session {
  id: string;
  course_id: string;
  course_code: string;
  course_name: string;
  name: string;
  session_type: string;
  scheduled_start: string;
  scheduled_end: string;
  checkin_opens_at: string;
  checkin_closes_at: string;
  venue_name: string;
  status: "scheduled" | "active" | "closed" | "cancelled";
  require_liveness_check: boolean;
  require_face_match: boolean;
}