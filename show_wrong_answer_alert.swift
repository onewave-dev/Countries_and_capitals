func showWrongAnswerAlert() {
    let alert = UIAlertController(
        title: "❌ Неверно.",
        message: "Правильный ответ:\n🇳🇬 Нигерия",
        preferredStyle: .alert
    )

    alert.addAction(UIAlertAction(title: "OK", style: .default))
    present(alert, animated: true)
}
