document.addEventListener("DOMContentLoaded", () => {

    // Initialize AOS
    if (typeof AOS !== "undefined") {
        AOS.init({
            duration: 800,
            once: true
        });
    }

    // Animate progress bars
    document.querySelectorAll(".progress-bar").forEach(bar => {
        const width = bar.style.width;
        bar.style.width = "0%";

        setTimeout(() => {
            bar.style.transition = "width 1.5s ease";
            bar.style.width = width;
        }, 300);
    });

    // Count-up animation
    document.querySelectorAll(".score-card h2").forEach(el => {

        const text = el.innerText.trim();

        if (!text.includes("%")) return;

        const target = parseFloat(text);

        let count = 0;

        const speed = target / 50;
        const precision = 3;

        const timer = setInterval(() => {

            count += speed;

            if (count >= target) {

                count = target;

                clearInterval(timer);

            }

            el.innerText = count.toFixed(precision) + "%";

        }, 20);

    });

    // Auto-scroll to results
    const results = document.getElementById("results");

    if (results) {

        results.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });

    }

});
document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("uploadForm");

    if (!form) return;

    form.addEventListener("submit", function () {

        const button = document.getElementById("submitBtn");

        const text = document.getElementById("btnText");

        const spinner = document.getElementById("loadingSpinner");

        button.disabled = true;

        text.style.display = "none";

        spinner.style.display = "inline-block";
        const aiLoader = document.getElementById("aiLoader");
        if (aiLoader) aiLoader.hidden = false;

    });

});

document.addEventListener("DOMContentLoaded", function () {
    const uploadCard = document.querySelector(".upload-card");
    const uploadForm = document.getElementById("uploadForm");
    if (!uploadCard || !uploadForm) return;

    ["dragenter", "dragover"].forEach(eventName => uploadCard.addEventListener(eventName, event => {
        event.preventDefault();
        uploadCard.classList.add("drag-active");
    }));
    ["dragleave", "drop"].forEach(eventName => uploadCard.addEventListener(eventName, event => {
        event.preventDefault();
        uploadCard.classList.remove("drag-active");
    }));
});

document.addEventListener("DOMContentLoaded", function () {
    const askButton = document.getElementById("askQuestionBtn");
    const candidateSelect = document.getElementById("candidateSelect");
    const questionInput = document.getElementById("interviewQuestion");
    const answerBox = document.getElementById("interviewAnswer");

    if (!askButton || !candidateSelect || !questionInput || !answerBox) return;

    const showMessage = (title, message) => {
        answerBox.hidden = false;
        answerBox.replaceChildren();
        const heading = document.createElement("h5");
        heading.textContent = title;
        const text = document.createElement("p");
        text.textContent = message;
        answerBox.append(heading, text);
    };

    const showAnswers = (candidate, answers, historyId) => {
        answerBox.hidden = false;
        answerBox.replaceChildren();
        const heading = document.createElement("h5");
        heading.textContent = `${answers.length} answer${answers.length === 1 ? "" : "s"} for ${candidate}`;
        const list = document.createElement("div");
        list.className = "answer-list";

        answers.forEach((item, index) => {
            const card = document.createElement("article");
            card.className = "answer-card";
            const question = document.createElement("h6");
            question.textContent = `${index + 1}. ${item.question}`;
            const status = document.createElement("span");
            status.className = "badge bg-primary answer-status";
            status.textContent = item.status || "review";
            question.append(" ", status);
            const answer = document.createElement("p");
            answer.textContent = item.answer;
            const evidence = document.createElement("p");
            evidence.innerHTML = "<strong>Resume evidence:</strong> ";
            evidence.append(document.createTextNode(item.evidence || "No supporting evidence found."));
            card.append(question, answer, evidence);
            list.append(card);
        });
        answerBox.append(heading, list);
        if (historyId) {
            const historyLink = document.createElement("a");
            historyLink.className = "btn btn-outline-primary btn-sm mt-3";
            historyLink.href = `/interview-history/${historyId}`;
            historyLink.innerHTML = '<i class="bi bi-bookmark-check"></i> View saved answers';
            answerBox.append(historyLink);
        }
    };

    const setCandidateFromUrl = () => {
        const candidateId = new URLSearchParams(window.location.search).get("candidate");
        if (candidateId) candidateSelect.value = candidateId;
    };
    setCandidateFromUrl();

    askButton.addEventListener("click", async function () {
        const candidateId = candidateSelect.value;
        const questions = questionInput.value.split("\n").map(question => question.trim()).filter(Boolean);

        if (!candidateId || !questions.length) {
            showMessage("Questions required", "Please select a candidate and add at least one question.");
            return;
        }

        askButton.disabled = true;
        askButton.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Answering...';
        showMessage("Preparing answers...", `The AI is answering all ${questions.length} question${questions.length === 1 ? "" : "s"}.`);

        try {
            const response = await fetch("/api/interview-answer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidate_id: candidateId, questions })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Unable to generate answers.");
            showAnswers(data.candidate, data.answers, data.history_id);
        } catch (error) {
            showMessage("Unable to answer right now", error.message);
        } finally {
            askButton.disabled = false;
            askButton.innerHTML = '<i class="bi bi-send-fill"></i> Get Answers';
        }
    });

    questionInput.addEventListener("keydown", function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") askButton.click();
    });
});

document.addEventListener("DOMContentLoaded", function () {
    const toggle = document.getElementById("themeToggle");
    const savedTheme = localStorage.getItem("smartHireTheme");
    if (savedTheme === "dark") document.body.classList.add("dark-theme");

    const refreshThemeIcon = () => {
        if (!toggle) return;
        toggle.innerHTML = document.body.classList.contains("dark-theme")
            ? '<i class="bi bi-sun-fill"></i>'
            : '<i class="bi bi-moon-stars-fill"></i>';
    };
    refreshThemeIcon();
    toggle?.addEventListener("click", () => {
        document.body.classList.toggle("dark-theme");
        localStorage.setItem("smartHireTheme", document.body.classList.contains("dark-theme") ? "dark" : "light");
        refreshThemeIcon();
    });
});
