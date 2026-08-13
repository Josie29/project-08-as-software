/**
 * Placeholder data for screens whose APIs are not built yet.
 *
 * Everything here is invented and clearly marked as such in the UI. It exists so each
 * screen's layout, states and accessibility can be finished and reviewed before the
 * backend lands; the issues that build those endpoints replace these imports outright.
 *
 * Nothing in this file is patient data, and nothing here should ever be presented to a
 * real user as though it came from the API.
 */

/** Rail badge counts until the real endpoints report them. */
export const MOCK_RAIL_COUNTS: Record<string, number> = {
  "/reports": 2,
  "/shares": 1,
  "/appointments": 1,
};

/** A finalised report, rendered in full. */
export const MOCK_SIGNED_REPORT = {
  title: "Obstetric Ultrasound — Second Trimester Anatomy Survey",
  clinic: "Northside Diagnostic Ultrasound",
  meta: [
    { label: "Patient", value: "AS-100241" },
    { label: "Exam date", value: "2026-08-02" },
    { label: "Accession", value: "8841-02" },
    { label: "Gestational age", value: "20w 3d" },
  ],
  indication: "Routine second-trimester anatomic survey. Singleton intrauterine pregnancy.",
  measurements: [
    { label: "Biparietal diameter", value: "5.21 cm · 48th pct" },
    { label: "Head circumference", value: "18.40 cm" },
    { label: "Abdominal circumference", value: "15.72 cm" },
    { label: "Femur length", value: "3.28 cm" },
    { label: "Amniotic fluid index", value: "14.1 cm · normal" },
    { label: "Fetal heart rate", value: "148 bpm · regular" },
  ],
  findings:
    "Visualized intracranial anatomy, four-chamber heart, stomach, kidneys, bladder, and spine appear within normal limits for gestational age. Placenta posterior, grade 0, clear of the internal os. No sonographic markers of aneuploidy identified.",
  impression:
    "Normal second-trimester anatomic survey. Growth appropriate for stated dates. Routine follow-up in four weeks.",
  signedBy: "Lena Okafor, MD — Diagnostic Radiology",
  stamp: "Electronically signed 2026-08-03 09:12 CT · SHA-256 3f9a…c710",
};

/** Status of a share link as the patient sees it. */
export type ShareStatus = "active" | "expired" | "revoked";

/** One share link row. */
export interface MockShare {
  id: string;
  resource: string;
  recipient: string;
  expiresLabel: string;
  token: string;
  status: ShareStatus;
}

export const MOCK_SHARES: MockShare[] = [
  {
    id: "s1",
    resource: "Anatomy survey · IMG-0004",
    recipient: "dr.reyes@example-clinic.test",
    expiresLabel: "Expires in 41 hours",
    token: "9f3c2a71b0e84d5f",
    status: "active",
  },
  {
    id: "s2",
    resource: "Dating scan report",
    recipient: "partner@example.test",
    expiresLabel: "Expired 3 days ago",
    token: "41ba77e0c9d24e18",
    status: "expired",
  },
  {
    id: "s3",
    resource: "Anatomy survey · IMG-0001",
    recipient: "mum@example.test",
    expiresLabel: "Switched off 6 days ago",
    token: "0c58d3f9a1764b22",
    status: "revoked",
  },
];
