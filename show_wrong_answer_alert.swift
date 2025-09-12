func showWrongAnswerAlert() {
    let alert = UIAlertController(
        title: "❌ Неверно.",
        message: "Правильный ответ:\n🇲🇿 Мозамбик",
        preferredStyle: .alert
    )

    alert.addAction(UIAlertAction(title: "OK", style: .default))
    present(alert, animated: true)
}
