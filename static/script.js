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

        const timer = setInterval(() => {

            count += speed;

            if (count >= target) {

                count = target;

                clearInterval(timer);

            }

            el.innerText = count.toFixed(0) + "%";

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

    });

});