// Course & Education Reformulator (SPEC-021)
// Local-first UI helper: displays reformulated courses without inventing data.

(function () {
  "use strict";

  function renderCourse(course) {
    const original = course.original_title || "";
    const adapted = course.adapted_title || original;
    const link = course.link_to_stage || "";
    const refs = (course.evidence_refs || []).join(", ");
    return (
      "<li>" +
      "<strong>" + adapted + "</strong>" +
      " <span title=\"cours réel: " + original + "\">(" + original + ")</span>" +
      (link ? "<br><small>" + link + "</small>" : "") +
      (refs ? "<br><small>preuves: " + refs + "</small>" : "") +
      "</li>"
    );
  }

  function renderPlan(plan) {
    const courses = (plan && plan.courses) || [];
    const reordered = (plan && plan.reordered_list) || [];
    const boosted = (plan && plan.certifications_boosted) || [];
    let html = "<ul>" + courses.map(renderCourse).join("") + "</ul>";
    html += "<p>Ordre adapté: " + reordered.join(", ") + "</p>";
    if (boosted.length) {
      html += "<p>Certifications mises en avant: " + boosted.join(", ") + "</p>";
    }
    return html;
  }

  window.CourseReformulator = {
    renderPlan: renderPlan,
    renderCourse: renderCourse,
  };
})();
