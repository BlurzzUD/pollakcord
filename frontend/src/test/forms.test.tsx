import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

import { findComments } from "../../scripts/check-no-comments.mjs";
import { ApiError, api } from "../api/client";
import type { AppNotification, FormDetail, FormQuestion, FormResults, FormSummary, Me } from "../api/types";
import { HomeSidebar } from "../components/layout/HomeSidebar";
import i18n from "../i18n";
import de from "../i18n/locales/de.json";
import en from "../i18n/locales/en.json";
import hu from "../i18n/locales/hu.json";
import { FormPage } from "../pages/FormPage";
import { FormResultsPage } from "../pages/FormResultsPage";
import { FormsPage } from "../pages/FormsPage";
import { NotificationsSection } from "../pages/settings/NotificationsSection";
import { useUi } from "../store/ui";
import { answerProblems, buildAnswers, draftProblem, emptyAnswers, emptyDraft, percentage, toCreateBody } from "../utils/forms";
import { describeNotification } from "../utils/notifications";
import { canCreateForms } from "../utils/roles";
import { makeMe, renderApp, resetLanguage, signIn, signOut } from "./helpers";

const mocked = vi.mocked(api);
const stamp = "2026-03-02T10:00:00+00:00";

const questions: FormQuestion[] = [
  {
    id: "11",
    position: 0,
    type: "single_choice",
    label: "Mikor jó az ebédszünet?",
    required: true,
    options: [
      { id: "111", label: "Korán" },
      { id: "112", label: "Később" },
    ],
  },
  {
    id: "12",
    position: 1,
    type: "multiple_choice",
    label: "Mit főzzenek többet?",
    required: false,
    options: [
      { id: "121", label: "Tészta" },
      { id: "122", label: "Leves" },
    ],
  },
  { id: "13", position: 2, type: "short_text", label: "Kedvenc étel", required: false, options: [] },
  { id: "14", position: 3, type: "long_text", label: "Egyéb észrevétel", required: true, options: [] },
];

function summary(overrides: Partial<FormSummary> = {}): FormSummary {
  return {
    id: "700",
    title: "Menza felmérés",
    description: "Pár gyors kérdés az ebédről.",
    target: { type: "school" },
    status: "open",
    creator_role: "dok_president",
    created_at: stamp,
    closed_at: null,
    question_count: 4,
    targeted: true,
    submitted: false,
    submitted_at: null,
    can_fill: true,
    can_manage: false,
    can_view_results: false,
    response_count: null,
    creator: null,
    ...overrides,
  };
}

function detail(overrides: Partial<FormDetail> = {}): FormDetail {
  return { ...summary(), questions, ...overrides };
}

const anna = { id: "9", username: "mate_anna", display_name: "Anna", avatar_url: null, staff: false };
const bence = { id: "10", username: "out_bence", display_name: "Bence", avatar_url: null, staff: false };

const firstPage: FormResults = {
  total: 3,
  has_more: true,
  summary: [
    {
      question_id: "11",
      type: "single_choice",
      answered: 3,
      options: [
        { id: "111", label: "Korán", count: 2 },
        { id: "112", label: "Később", count: 1 },
      ],
    },
    {
      question_id: "12",
      type: "multiple_choice",
      answered: 1,
      options: [
        { id: "121", label: "Tészta", count: 1 },
        { id: "122", label: "Leves", count: 0 },
      ],
    },
    { question_id: "13", type: "short_text", answered: 1, options: [] },
    { question_id: "14", type: "long_text", answered: 3, options: [] },
  ],
  responses: [
    { id: "903", user: bence, submitted_at: stamp, answers: { "11": { options: ["112"] }, "14": { text: "Jó lenne több saláta." } } },
    {
      id: "902",
      user: anna,
      submitted_at: stamp,
      answers: { "11": { options: ["111"] }, "12": { options: ["121"] }, "13": { text: "Gulyás" }, "14": { text: "Minden rendben" } },
    },
  ],
};

const secondPage: FormResults = {
  ...firstPage,
  has_more: false,
  responses: [{ id: "901", user: null, submitted_at: stamp, answers: { "11": { options: ["111"] }, "14": null } }],
};

function serve(responses: Record<string, unknown>) {
  mocked.get.mockImplementation(async (path: string) => {
    if (path in responses) {
      return responses[path];
    }
    throw new ApiError(404, "not_found", "x");
  });
}

function translate(key: string, options?: Record<string, unknown>): string {
  return i18n.t(key, options) as string;
}

function renderForm(form: FormDetail) {
  serve({ "/forms/700": form });
  return renderApp(
    <Routes>
      <Route path="/app/forms/:formId" element={<FormPage />} />
    </Routes>,
    "/app/forms/700",
  );
}

function renderResults() {
  return renderApp(
    <Routes>
      <Route path="/app/forms/:formId/results" element={<FormResultsPage />} />
    </Routes>,
    "/app/forms/700/results",
  );
}

beforeEach(() => {
  resetLanguage();
  signOut();
  Object.values(mocked).forEach((fn) => fn.mockReset());
  useUi.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  resetLanguage();
});

const creators: [Me["platform_role"], boolean][] = [
  ["user", false],
  ["dok_representative", false],
  ["dok_president", true],
  ["school_moderator", true],
  ["school_admin", true],
];

describe("who may create forms", () => {
  it("is limited to the school admin, moderators and the DÖK president", () => {
    expect(creators.filter(([role]) => canCreateForms(role)).map(([role]) => role)).toEqual(["dok_president", "school_moderator", "school_admin"]);
    expect(canCreateForms(null)).toBe(false);
    expect(canCreateForms(undefined)).toBe(false);
  });

  it.each(creators)("shows the create button for %s: %s", async (role, allowed) => {
    signIn(makeMe({ platform_role: role, class_code: "9A" }));
    serve({ "/forms": { items: [] } });
    renderApp(<FormsPage />, "/app/forms");
    expect(await screen.findByText("Még nincs űrlap")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Új űrlap/ }) !== null).toBe(allowed);
  });

  it("does not ask the server for forms when someone has no class and cannot create any", async () => {
    signIn(makeMe());
    serve({});
    renderApp(<FormsPage />, "/app/forms");
    expect(await screen.findByText("Még nincs űrlap")).toBeInTheDocument();
    expect(mocked.get.mock.calls.some(([path]) => path === "/forms")).toBe(false);
  });
});

describe("forms list", () => {
  it("groups forms into to-fill, answered and manageable sections", async () => {
    signIn(makeMe({ platform_role: "dok_president", class_code: "9A" }));
    const waiting = summary({ id: "700", title: "Menza felmérés" });
    const sent = summary({ id: "701", title: "Tanévzáró", can_fill: false, submitted: true, submitted_at: stamp });
    const closed = summary({ id: "702", title: "Régi kérdőív", can_fill: false, status: "closed", closed_at: stamp });
    const mine = summary({ id: "703", title: "Saját felmérés", targeted: false, can_fill: false, can_manage: true, can_view_results: true, response_count: 3 });
    serve({ "/forms": { items: [mine, closed, sent, waiting] } });
    renderApp(<FormsPage />, "/app/forms");

    const fill = await screen.findByRole("region", { name: "Kitöltendő" });
    expect(within(fill).getByRole("link", { name: "Menza felmérés" })).toHaveAttribute("href", "/app/forms/700");
    expect(within(fill).getByRole("link", { name: "Kitöltés" })).toHaveAttribute("href", "/app/forms/700");
    expect(within(fill).queryByText("Tanévzáró")).not.toBeInTheDocument();

    const done = screen.getByRole("region", { name: "Kitöltött vagy lezárt" });
    expect(within(done).getByText("Tanévzáró")).toBeInTheDocument();
    expect(within(done).getByText("Kitöltve")).toBeInTheDocument();
    expect(within(done).getByText("Régi kérdőív")).toBeInTheDocument();
    expect(within(done).getByText("Lezárt")).toBeInTheDocument();
    expect(within(done).queryByText("Saját felmérés")).not.toBeInTheDocument();
    expect(within(done).queryByText("Menza felmérés")).not.toBeInTheDocument();

    const manage = screen.getByRole("region", { name: "Kezelés és eredmények" });
    expect(within(manage).getByText("Saját felmérés")).toBeInTheDocument();
    expect(within(manage).getByText("3 válasz")).toBeInTheDocument();
    expect(within(manage).getByRole("link", { name: "Eredmények" })).toHaveAttribute("href", "/app/forms/703/results");
  });

  it("lets the creator close and delete a form from the list", async () => {
    signIn(makeMe({ platform_role: "dok_president" }));
    const mine = summary({ targeted: false, can_fill: false, can_manage: true, can_view_results: true, response_count: 3 });
    serve({ "/forms": { items: [mine] } });
    mocked.patch.mockResolvedValue({ ...detail(), status: "closed" });
    mocked.del.mockResolvedValue({ status: "deleted" });
    renderApp(<FormsPage />, "/app/forms");

    fireEvent.click(await screen.findByRole("button", { name: "Űrlap lezárása" }));
    await waitFor(() => expect(mocked.patch).toHaveBeenCalledWith("/forms/700", { status: "closed" }));

    fireEvent.click(screen.getByRole("button", { name: "Törlés" }));
    const dialog = await screen.findByRole("dialog");
    expect(mocked.del).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Törlés" }));
    await waitFor(() => expect(mocked.del).toHaveBeenCalledWith("/forms/700"));
  });

  it("offers no management buttons for forms someone may only read results of", async () => {
    signIn(makeMe({ platform_role: "school_moderator" }));
    serve({ "/forms": { items: [summary({ targeted: false, can_fill: false, can_manage: false, can_view_results: true, response_count: 1 })] } });
    renderApp(<FormsPage />, "/app/forms");
    expect(await screen.findByRole("link", { name: "Eredmények" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Űrlap lezárása" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Törlés" })).not.toBeInTheDocument();
  });
});

describe("creating a form", () => {
  async function openEditor() {
    signIn(makeMe({ platform_role: "dok_president" }));
    serve({ "/forms": { items: [] }, "/me/classes": [{ id: "1001", code: "9A", grade: 9, section: "A" }] });
    renderApp(
      <Routes>
        <Route path="/app/forms" element={<FormsPage />} />
        <Route path="/app/forms/:formId/results" element={<p>Eredményoldal</p>} />
      </Routes>,
      "/app/forms",
    );
    fireEvent.click(await screen.findByRole("button", { name: /Új űrlap/ }));
    return screen.findByRole("dialog");
  }

  it("posts the cleaned form for the chosen class and opens its results", async () => {
    const dialog = await openEditor();
    mocked.post.mockResolvedValue(detail({ id: "701", can_manage: true, can_view_results: true }));
    fireEvent.change(within(dialog).getByLabelText("Cím"), { target: { value: "  Menza   felmérés " } });
    await within(dialog).findByRole("option", { name: "9A osztály" });
    fireEvent.change(within(dialog).getByLabelText("Kinek szól?"), { target: { value: "1001" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés típusa"), { target: { value: "single_choice" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés szövege"), { target: { value: "Mikor jó az ebédszünet?" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés, 1. válaszlehetőség"), { target: { value: "Korán" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés, 2. válaszlehetőség"), { target: { value: " Később " } });
    fireEvent.click(within(dialog).getByRole("switch", { name: "Kötelező" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Kérdés hozzáadása" }));
    fireEvent.change(within(dialog).getByLabelText("2. kérdés szövege"), { target: { value: "Egyéb észrevétel" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));

    await waitFor(() =>
      expect(mocked.post).toHaveBeenCalledWith("/forms", {
        title: "Menza felmérés",
        description: "",
        target: { type: "class", class_id: "1001" },
        questions: [
          { type: "single_choice", label: "Mikor jó az ebédszünet?", required: true, options: ["Korán", "Később"] },
          { type: "short_text", label: "Egyéb észrevétel", required: false, options: [] },
        ],
      }),
    );
    expect(await screen.findByText("Eredményoldal")).toBeInTheDocument();
  });

  it("defaults to the whole school", async () => {
    const dialog = await openEditor();
    mocked.post.mockResolvedValue(detail({ id: "702" }));
    fireEvent.change(within(dialog).getByLabelText("Cím"), { target: { value: "Iskolai szavazás" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés szövege"), { target: { value: "Mi legyen a jelmezes nap témája?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));
    await waitFor(() => expect(mocked.post).toHaveBeenCalled());
    expect(mocked.post.mock.calls[0][1]).toMatchObject({ target: { type: "school" } });
  });

  it("explains problems before anything is sent", async () => {
    const dialog = await openEditor();
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));
    expect(await within(dialog).findByText("A cím 1–120 karakter hosszú lehet, vezérlőkarakterek nélkül.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Cím"), { target: { value: "Cím" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));
    expect(await within(dialog).findByText("Minden kérdésnek kell címe, legfeljebb 200 karakterrel.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("1. kérdés szövege"), { target: { value: "Választ?" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés típusa"), { target: { value: "multiple_choice" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés, 1. válaszlehetőség"), { target: { value: "Igen" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés, 2. válaszlehetőség"), { target: { value: "igen" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));
    expect(
      await within(dialog).findByText("A választós kérdésekhez 2–12 különböző válaszlehetőség kell, egyenként legfeljebb 100 karakterrel."),
    ).toBeInTheDocument();
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("shows the server's refusal inside the dialog", async () => {
    const dialog = await openEditor();
    mocked.post.mockRejectedValue(new ApiError(403, "form_create_forbidden", "x"));
    fireEvent.change(within(dialog).getByLabelText("Cím"), { target: { value: "Cím" } });
    fireEvent.change(within(dialog).getByLabelText("1. kérdés szövege"), { target: { value: "Kérdés" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Közzététel" }));
    expect(await within(dialog).findByText("Űrlapot csak iskolai adminisztrátor, moderátor vagy a DÖK-elnök hozhat létre.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps question numbers unique and never allows removing the last question", async () => {
    const dialog = await openEditor();
    expect(within(dialog).getByRole("button", { name: "1. kérdés törlése" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Kérdés hozzáadása" }));
    expect(within(dialog).getByLabelText("2. kérdés szövege")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "1. kérdés törlése" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "2. kérdés törlése" }));
    expect(within(dialog).queryByLabelText("2. kérdés szövege")).not.toBeInTheDocument();
  });
});

describe("filling a form", () => {
  it("validates required answers on the client before anything is sent", async () => {
    signIn(makeMe({ class_code: "9A" }));
    renderForm(detail());
    expect(await screen.findByText("Pár gyors kérdés az ebédről.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Beküldés" }));
    expect(await screen.findAllByText("Válaszolj az összes kötelező kérdésre.")).toHaveLength(2);
    expect(mocked.post).not.toHaveBeenCalled();
  });

  it("submits the answers once and then shows the already-submitted state", async () => {
    signIn(makeMe({ class_code: "9A" }));
    mocked.post.mockResolvedValue({ form_id: "700", submitted: true, submitted_at: stamp });
    renderForm(detail());
    fireEvent.click(await screen.findByRole("radio", { name: "Korán" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Leves" }));
    fireEvent.change(screen.getByLabelText("Kedvenc étel"), { target: { value: "  Gulyás " } });
    fireEvent.change(screen.getByLabelText("Egyéb észrevétel"), { target: { value: "Minden rendben" } });
    fireEvent.click(screen.getByRole("button", { name: "Beküldés" }));

    await waitFor(() =>
      expect(mocked.post).toHaveBeenCalledWith("/forms/700/responses", {
        answers: [
          { question_id: "11", options: ["111"] },
          { question_id: "12", options: ["122"] },
          { question_id: "13", text: "Gulyás" },
          { question_id: "14", text: "Minden rendben" },
        ],
      }),
    );
    expect(await screen.findByText(/Ezt az űrlapot már kitöltötted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Beküldés" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(mocked.post).toHaveBeenCalledTimes(1);
  });

  it("only sends answers that were given and lets optional single choices be cleared", async () => {
    signIn(makeMe({ class_code: "9A" }));
    mocked.post.mockResolvedValue({ form_id: "700", submitted: true, submitted_at: stamp });
    const relaxed = questions.map((question) => ({ ...question, required: false }));
    renderForm(detail({ questions: relaxed }));
    fireEvent.click(await screen.findByRole("radio", { name: "Később" }));
    fireEvent.click(screen.getByRole("button", { name: "Választás törlése" }));
    expect(screen.getByRole("radio", { name: "Később" })).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("Egyéb észrevétel"), { target: { value: "Köszi" } });
    fireEvent.click(screen.getByRole("button", { name: "Beküldés" }));
    await waitFor(() => expect(mocked.post).toHaveBeenCalledWith("/forms/700/responses", { answers: [{ question_id: "14", text: "Köszi" }] }));
  });

  it("keeps the form and shows the server's reason when a submission is refused", async () => {
    signIn(makeMe({ class_code: "9A" }));
    mocked.post.mockRejectedValue(new ApiError(409, "form_closed", "x"));
    renderForm(detail());
    fireEvent.click(await screen.findByRole("radio", { name: "Korán" }));
    fireEvent.change(screen.getByLabelText("Egyéb észrevétel"), { target: { value: "Valami" } });
    fireEvent.click(screen.getByRole("button", { name: "Beküldés" }));
    expect(await screen.findByText("Az űrlap le van zárva, már nem fogad válaszokat.")).toBeInTheDocument();
    expect(screen.getByLabelText("Egyéb észrevétel")).toHaveValue("Valami");
  });

  it("shows the submitted state instead of the questions when the form was already answered", async () => {
    signIn(makeMe({ class_code: "9A" }));
    renderForm(detail({ submitted: true, submitted_at: stamp, can_fill: false }));
    expect(await screen.findByText(/Ezt az űrlapot már kitöltötted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Beküldés" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Egyéb észrevétel")).not.toBeInTheDocument();
  });

  it("explains closed forms without offering inputs", async () => {
    signIn(makeMe({ class_code: "9A" }));
    renderForm(detail({ status: "closed", closed_at: stamp, can_fill: false }));
    expect(await screen.findByText("Ez az űrlap le van zárva, már nem fogad válaszokat.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Beküldés" })).not.toBeInTheDocument();
  });

  it("tells staff outside the audience why they cannot fill the form and links to its results", async () => {
    signIn(makeMe({ platform_role: "school_moderator" }));
    renderForm(detail({ targeted: false, can_fill: false, can_view_results: true, response_count: 4 }));
    expect(await screen.findByText("Nem tartozol az űrlap címzettjei közé, ezért nem töltheted ki.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Eredmények" })).toHaveAttribute("href", "/app/forms/700/results");
    expect(screen.queryByRole("button", { name: "Beküldés" })).not.toBeInTheDocument();
  });

  it("shows only the role of the creator, never a person", async () => {
    signIn(makeMe({ class_code: "9A" }));
    renderForm(detail());
    expect(await screen.findByText("DÖK elnök")).toBeInTheDocument();
    expect(screen.getByText("Az egész iskola")).toBeInTheDocument();
  });

  it("says so when the form is not available", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({});
    renderApp(
      <Routes>
        <Route path="/app/forms/:formId" element={<FormPage />} />
      </Routes>,
      "/app/forms/700",
    );
    expect(await screen.findByText("Az űrlap nem érhető el")).toBeInTheDocument();
  });
});

describe("results page", () => {
  it("refuses people who may not see results and never asks for responses", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/forms/700": detail() });
    renderResults();
    expect(await screen.findByText("Az eredmények nem láthatók")).toBeInTheDocument();
    expect(mocked.get.mock.calls.some(([path]) => String(path).endsWith("/responses"))).toBe(false);
  });

  it("refuses forms that are hidden from the viewer", async () => {
    signIn(makeMe({ platform_role: "dok_president", class_code: "9A" }));
    serve({});
    renderResults();
    expect(await screen.findByText("Az eredmények nem láthatók")).toBeInTheDocument();
    expect(mocked.get.mock.calls.some(([path]) => String(path).endsWith("/responses"))).toBe(false);
  });

  it("shows choice counts, text answers with platform names and loads more on request", async () => {
    signIn(makeMe({ platform_role: "dok_president" }));
    mocked.get.mockImplementation(async (path: string, query?: Record<string, unknown>) => {
      if (path === "/forms/700") {
        return detail({ can_manage: true, can_view_results: true, response_count: 3 });
      }
      if (path === "/forms/700/responses") {
        return query?.before ? secondPage : firstPage;
      }
      throw new ApiError(404, "not_found", "x");
    });
    renderResults();

    expect(await screen.findByText("1. Mikor jó az ebédszünet?")).toBeInTheDocument();
    expect(screen.getByText("2 (67%)")).toBeInTheDocument();
    expect(screen.getByText("1 (33%)")).toBeInTheDocument();
    expect(screen.getByText("1 (100%)")).toBeInTheDocument();
    expect(screen.getByText("0 (0%)")).toBeInTheDocument();
    expect(screen.getByText("Gulyás")).toBeInTheDocument();
    const saláta = screen.getByText("Jó lenne több saláta.").closest("li") as HTMLElement;
    expect(within(saláta).getByText("Bence")).toBeInTheDocument();
    expect(within(saláta).getByText(/@out_bence/)).toBeInTheDocument();
    expect(screen.getByText("Az eredmények a válaszadók platformnevével jelennek meg, a valódi nevüket nem látod.")).toBeInTheDocument();
    expect(screen.getByText("2 / 3 válasz betöltve")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Szabó");

    fireEvent.click(screen.getByRole("button", { name: "Továbbiak betöltése" }));
    await waitFor(() => expect(mocked.get).toHaveBeenCalledWith("/forms/700/responses", { limit: 50, before: "902" }));
    expect(await screen.findByText("Törölt fiók")).toBeInTheDocument();
    expect(screen.getByText("Ez a válasz nem olvasható.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Továbbiak betöltése" })).not.toBeInTheDocument();
  });

  it("says when nobody has answered yet", async () => {
    signIn(makeMe({ platform_role: "school_admin" }));
    serve({
      "/forms/700": detail({ can_manage: true, can_view_results: true, response_count: 0 }),
      "/forms/700/responses": { total: 0, has_more: false, summary: [], responses: [] },
    });
    renderResults();
    expect(await screen.findByText("Még nem érkezett válasz")).toBeInTheDocument();
  });

  it("offers close and delete only to people who may manage the form", async () => {
    signIn(makeMe({ platform_role: "school_moderator" }));
    serve({
      "/forms/700": detail({ can_manage: false, can_view_results: true, response_count: 3 }),
      "/forms/700/responses": firstPage,
    });
    renderResults();
    expect(await screen.findByText("1. Mikor jó az ebédszünet?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Űrlap lezárása" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Törlés" })).not.toBeInTheDocument();
  });
});

describe("navigation and notifications", () => {
  it("adds a Forms entry to the sidebar with the number of forms waiting", async () => {
    signIn(makeMe({ class_code: "9A" }));
    serve({ "/forms": { items: [summary(), summary({ id: "701", can_fill: false, submitted: true })] } });
    renderApp(<HomeSidebar />, "/app");
    expect(await screen.findByRole("link", { name: /^Űrlapok\s*1$/ })).toHaveAttribute("href", "/app/forms");
  });

  it("keeps the entry for people without forms and does not ask the server about them", async () => {
    signIn(makeMe());
    serve({});
    renderApp(<HomeSidebar />, "/app");
    expect(await screen.findByRole("link", { name: "Űrlapok" })).toHaveAttribute("href", "/app/forms");
    expect(mocked.get.mock.calls.some(([path]) => path === "/forms")).toBe(false);
  });

  const note = (payload: Record<string, unknown>): AppNotification => ({ id: "1", type: "form_available", payload, read: false, created_at: stamp });

  it("describes new forms and links to them", () => {
    const wide = describeNotification(translate, note({ form_id: "700", title: "Menza felmérés", scope: "school", class_code: null }));
    expect(wide.text).toBe("Új űrlap: Menza felmérés (Az egész iskola).");
    expect(wide.href).toBe("/app/forms/700");
    const own = describeNotification(translate, note({ form_id: "701", title: "9A kérdőív", scope: "class", class_code: "9A" }));
    expect(own.text).toBe("Új űrlap: 9A kérdőív (9A osztály).");
    expect(own.href).toBe("/app/forms/701");
  });

  it("lets people switch form notifications off in the settings", async () => {
    signIn(makeMe());
    mocked.patch.mockResolvedValue(makeMe());
    renderApp(<NotificationsSection />);
    const toggle = screen.getByRole("switch", { name: "Űrlapok" });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(mocked.patch).toHaveBeenCalledWith("/me/settings", { notification_prefs: { forms: false } }));
  });
});

describe("form helpers", () => {
  it("mirrors the server's validation for new forms", () => {
    const draft = emptyDraft();
    expect(draftProblem(draft)?.code).toBe("form_title_invalid");
    draft.title = "Cím";
    expect(draftProblem(draft)?.code).toBe("form_question_invalid");
    draft.questions[0].label = "Kérdés";
    expect(draftProblem(draft)).toBeNull();
    draft.questions[0].type = "single_choice";
    draft.questions[0].options = ["Igen"];
    expect(draftProblem(draft)?.code).toBe("form_options_invalid");
    draft.questions[0].options = ["Igen", " igen "];
    expect(draftProblem(draft)?.code).toBe("form_options_invalid");
    draft.questions[0].options = [" Igen ", "Nem"];
    expect(draftProblem(draft)).toBeNull();
    expect(toCreateBody(draft).questions[0].options).toEqual(["Igen", "Nem"]);
    draft.title = "x".repeat(121);
    expect(draftProblem(draft)?.params).toEqual({ max: 120 });
  });

  it("flags missing required answers and over-long text, and builds only given answers", () => {
    const answers = emptyAnswers(questions);
    expect(Object.keys(answerProblems(questions, answers)).sort()).toEqual(["11", "14"]);
    answers["11"] = { text: "", options: ["111"] };
    answers["13"] = { text: "é".repeat(201), options: [] };
    answers["14"] = { text: "  rendben ", options: [] };
    expect(answerProblems(questions, answers)).toEqual({ "13": { code: "form_answer_too_long", params: { max: 200 } } });
    answers["13"] = { text: "", options: [] };
    expect(buildAnswers(questions, answers)).toEqual([
      { question_id: "11", options: ["111"] },
      { question_id: "14", text: "rendben" },
    ]);
  });

  it("rounds shares and copes with an empty total", () => {
    expect(percentage(1, 3)).toBe(33);
    expect(percentage(2, 3)).toBe(67);
    expect(percentage(0, 0)).toBe(0);
  });
});

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const flat: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === "string") {
      flat[prefix + key] = value;
    } else {
      Object.assign(flat, flatten(value, `${prefix}${key}.`));
    }
  }
  return flat;
}

describe("forms translations and hygiene", () => {
  const catalogs = { hu: flatten(hu as Tree), en: flatten(en as Tree), de: flatten(de as Tree) };
  const hasKey = (catalog: Record<string, string>, key: string) => key in catalog || `${key}_one` in catalog || `${key}_other` in catalog;
  const placeholders = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((match) => match[1]).sort();
  const sources = [
    "pages/FormsPage.tsx",
    "pages/FormPage.tsx",
    "pages/FormResultsPage.tsx",
    "components/forms/FormEditorDialog.tsx",
    "components/forms/FormManageActions.tsx",
    "components/forms/FormQuestionField.tsx",
    "utils/forms.ts",
    "utils/notifications.ts",
    "components/layout/HomeSidebar.tsx",
  ];

  it("has the same forms keys and placeholders in Hungarian, English and German", () => {
    const own = (catalog: Record<string, string>) => Object.keys(catalog).filter((key) => key.startsWith("forms.") || key.startsWith("errors.form_")).sort();
    expect(own(catalogs.hu).length).toBeGreaterThan(70);
    expect(own(catalogs.en)).toEqual(own(catalogs.hu));
    expect(own(catalogs.de)).toEqual(own(catalogs.hu));
    for (const key of own(catalogs.hu)) {
      expect(placeholders(catalogs.en[key]), key).toEqual(placeholders(catalogs.hu[key]));
      expect(placeholders(catalogs.de[key]), key).toEqual(placeholders(catalogs.hu[key]));
      expect(catalogs.hu[key].trim(), key).not.toBe("");
    }
  });

  it("defines every translation key the forms source uses", () => {
    const used = new Set<string>();
    for (const file of sources) {
      for (const match of readFileSync(join(__dirname, "..", file), "utf8").matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"/g)) {
        used.add(match[1]);
      }
    }
    expect([...used].filter((key) => key.startsWith("forms.")).length).toBeGreaterThan(40);
    for (const [language, catalog] of Object.entries(catalogs)) {
      expect([...used].filter((key) => !hasKey(catalog, key)), language).toEqual([]);
    }
  });

  it("defines the dynamically built keys", () => {
    const expected = [
      ...["short_text", "long_text", "single_choice", "multiple_choice"].map((type) => `forms.type_${type}`),
      ...["open", "closed", "submitted"].map((status) => `forms.status_${status}`),
      ...["form_create", "form_update", "form_close", "form_reopen", "form_delete", "form_results_view"].map((action) => `audit.actions.${action}`),
      "notifications.pref_forms",
      "notifications.pref_forms_hint",
      "notifications.form_available",
      "nav.forms",
    ];
    for (const [language, catalog] of Object.entries(catalogs)) {
      expect(expected.filter((key) => !hasKey(catalog, key)), language).toEqual([]);
    }
  });

  it("translates every form error code the backend can return", () => {
    const backend = JSON.parse(readFileSync(join(__dirname, "../../../backend/app/locales/hu.json"), "utf8")).errors as Record<string, string>;
    const codes = Object.keys(backend).filter((code) => code.startsWith("form_"));
    expect(codes.length).toBe(14);
    for (const [language, catalog] of Object.entries(catalogs)) {
      expect(codes.filter((code) => !(`errors.${code}` in catalog)), language).toEqual([]);
    }
  });

  it("keeps the new files free of comments", () => {
    expect(findComments().filter((entry: string) => /Form|forms/.test(entry))).toEqual([]);
  });
});
