let timeLeft = 10 * 60;

const timerDisplay = document.getElementById("timer");
const examForm = document.getElementById("examForm");

const countdown = setInterval(function () {

    let minutes = Math.floor(timeLeft / 60);
    let seconds = timeLeft % 60;

    timerDisplay.textContent =
        String(minutes).padStart(2, "0") + ":" +
        String(seconds).padStart(2, "0");

    if (timeLeft <= 0) {
        clearInterval(countdown);

        alert("Time is over! Your examination will be submitted.");

        examForm.submit();
    }

    timeLeft--;

}, 1000);