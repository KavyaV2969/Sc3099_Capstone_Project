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

export interface Enrollment {
  id: string;
  course_id: string;
  course_code: string;
  course_name: string;
  semester: string;
  instructor_name: string;
  is_active: boolean;
  enrolled_at: string;
}

export interface Device {
  id: string;
  device_fingerprint: string;
  device_name: string | null;
  platform: string | null;
  is_trusted: boolean;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string | null;
  total_checkins: number;
}

export interface Checkin {
  id: string;
  session_id: string;
  checked_in_at: string;
  status: "approved" | "flagged" | "rejected" | "appealed";
  risk_score: number;
  distance_from_venue_meters: number;
  location_accuracy_meters: number | null;
  liveness_passed: boolean | null;
  face_match_passed: boolean | null;
  risk_factors: { type: string }[];
  review_notes: string | null;
  appeal_reason: string | null;
  appealed_at: string | null;
  session_name: string | null;
  course_code: string | null;
}