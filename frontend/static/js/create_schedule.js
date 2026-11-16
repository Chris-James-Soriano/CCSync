(() => {
  const form = document.getElementById("schedule-form");
  const checkButton = document.getElementById("check-schedule");
  const summary = document.getElementById("check-summary");
  const results = document.getElementById("check-results");

  if (!form || !checkButton || !summary || !results) return;

  const schedules = [
    { day: "THU", start: 11, end: 14, room: "Room 206", instructor: "Sir Sotomayor", section: "BSCS 3A", course: "CMSC 308" },
    { day: "THU", start: 11, end: 14, room: "Room 206", instructor: "Sir Reyes", section: "BSCS 3A", course: "CMSC 306" },
    { day: "TUE", start: 9, end: 12, room: "MAC LAB", instructor: "Sample Faculty", section: "BSIT 2A", course: "CMSC 201" },
  ];
  const roomOptions = Array.from(form.querySelectorAll(".room-option"));
  const dayInputs = Array.from(form.querySelectorAll('input[name="day"]'));
  const checkItems = {
    room: results.querySelector('[data-check="room"]'),
    instructor: results.querySelector('[data-check="instructor"]'),
    section: results.querySelector('[data-check="section"]'),
  };

  const normalized = (value) => value.trim().toLocaleLowerCase();
  const timeLabel = (hour) => {
    const suffix = hour < 12 ? "AM" : "PM";
    const displayHour = hour % 12 || 12;
    return `${displayHour}:00 ${suffix}`;
  };

  function runChecks() {
    const course = form.elements.course.value.trim();
    const section = form.elements.section.value.trim();
    const instructor = form.elements.instructor.value.trim();
    const start = Number(form.elements.start.value);
    const end = Number(form.elements.end.value);
    const days = dayInputs.filter((input) => input.checked).map((input) => input.value);
    const hasDetails = course && section && instructor && days.length > 0
      && form.elements.start.value && form.elements.end.value;
    const hasValidTime = hasDetails && end > start;

    roomOptions.forEach((option) => {
      const roomInput = option.querySelector('input[name="room"]');
      const roomName = normalized(roomInput.value);
      const conflicts = schedules.filter((item) =>
        days.includes(item.day)
        && normalized(item.room) === roomName
        && item.start < end
        && item.end > start
      );
      const status = option.querySelector(".room-status");
      const unavailable = hasValidTime && conflicts.length > 0;
      roomInput.disabled = unavailable;
      option.classList.toggle("is-unavailable", unavailable);
      option.classList.toggle("is-available", hasValidTime && !unavailable);
      status.textContent = !hasValidTime
        ? "Choose a time"
        : unavailable
          ? "Conflict"
          : "Available";
      if (unavailable && roomInput.checked) roomInput.checked = false;
    });

    if (!hasDetails) {
      summary.textContent = "Complete the course, section, instructor, day, and valid time range to run checks.";
      Object.values(checkItems).forEach((item) => {
        item.textContent = `${item.textContent.split(":")[0]}: awaiting details`;
        item.className = "";
      });
      return;
    }

    if (!hasValidTime) {
      summary.textContent = "End time must be later than start time.";
      Object.values(checkItems).forEach((item) => {
        item.className = "";
      });
      return;
    }

    const selectedRoom = form.querySelector('input[name="room"]:checked');
    const overlapping = schedules.filter((item) =>
      days.includes(item.day) && item.start < end && item.end > start
    );
    const roomConflicts = selectedRoom
      ? overlapping.filter((item) => normalized(item.room) === normalized(selectedRoom.value))
      : [];
    const instructorConflicts = overlapping.filter((item) =>
      normalized(item.instructor) === normalized(instructor)
    );
    const sectionConflicts = overlapping.filter((item) =>
      normalized(item.section) === normalized(section)
    );

    const setCheck = (key, label, conflicts) => {
      const item = checkItems[key];
      item.className = conflicts.length ? "check-conflict" : "check-clear";
      item.textContent = conflicts.length
        ? `${label}: conflict with ${conflicts.map((entry) => `${entry.course} / ${entry.section} (${entry.day} ${timeLabel(entry.start)}–${timeLabel(entry.end)})`).join("; ")}`
        : `${label}: no conflicts`;
    };

    if (selectedRoom) {
      setCheck("room", `Room (${selectedRoom.value})`, roomConflicts);
    } else {
      const availableCount = roomOptions.filter((option) => !option.querySelector('input[name="room"]').disabled).length;
      checkItems.room.className = availableCount ? "" : "check-conflict";
      checkItems.room.textContent = availableCount
        ? `Room: select one of ${availableCount} available rooms`
        : "Room: no rooms are available for this day and time";
    }
    setCheck("instructor", `Instructor (${instructor})`, instructorConflicts);
    setCheck("section", `Section / students (${section})`, sectionConflicts);

    const conflictsFound = roomConflicts.length + instructorConflicts.length + sectionConflicts.length;
    summary.textContent = conflictsFound
      ? `${conflictsFound} conflict check${conflictsFound === 1 ? "" : "s"} found. Choose another room or time, or review the affected faculty/section.`
      : selectedRoom
        ? "All checks passed for the selected room, instructor, section, day, and time."
        : "No faculty or section conflicts found. Select one of the available rooms.";
  }

  form.addEventListener("input", runChecks);
  form.addEventListener("change", runChecks);
  checkButton.addEventListener("click", runChecks);
  runChecks();
})();
