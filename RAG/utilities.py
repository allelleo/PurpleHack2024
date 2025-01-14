import torch
from transformers import AutoModel, AutoTokenizer, pipeline, Conversation
from typing import List, Dict, Union
from config import SYSTEM_PROMPT


def search_results(connection, table_name: str, vector: list[float], limit: int = 5):
    """
    Поиск результатов похожих векторов в базе данных.

    Parameters:
    - connection (Connection): Соединение с базой данных.
    - table_name (str): Название таблицы, содержащей вектора и другие данные.
    - vector (List[float]): Вектор для сравнения.
    - limit (int): Максимальное количество результатов.

    Returns:
    - List[dict]: Список результатов с наименованием, URL, датой, номером, текстом и расстоянием.

    Examples:
    >>> connection = Connection(...)
    >>> vector = [0.1, 0.2, 0.3]
    >>> results = search_results(connection, 'my_table', vector, limit=5)
    """
    res = []
    # Инициализируем список результатов
    vector = ",".join([str(float(i)) for i in vector])
    # Выполняем запрос к базе данных
    with connection.query(
        f"SELECT Name, Url, Date, Number, Text, cosineDistance(({vector}), Embedding) as score FROM {table_name} ORDER BY score DESC LIMIT {limit}"
    ).rows_stream as stream:
        for item in stream:
            name, url, date, num, text, score = item

            # Добавляем результат в список
            res.append(
                {
                    "name": name,
                    "url": url,
                    "date": date,
                    "num": num,
                    "text": text,
                    "dist": score,
                }
            )

    # Возвращаем первые limit результатов
    return res[:limit]


def mean_pooling(model_output: tuple, attention_mask: torch.Tensor) -> torch.Tensor:
    """
    Выполняет усреднение токенов входной последовательности на основе attention mask.

    Parameters:
    - model_output (tuple): Выход модели, включающий токенов эмбеддинги и другие данные.
    - attention_mask (torch.Tensor): Маска внимания для указания значимости токенов.

    Returns:
    - torch.Tensor: Усредненный эмбеддинг.

    Examples:
    >>> embeddings = model_output[0]
    >>> mask = torch.tensor([[1, 1, 1, 0, 0]])
    >>> pooled_embedding = mean_pooling((embeddings,), mask)
    """
    # Получаем эмбеддинги токенов из выхода модели
    token_embeddings = model_output[0]

    # Расширяем маску внимания для умножения с эмбеддингами
    input_mask_expanded = (
        attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    )

    # Умножаем каждый токен на его маску и суммируем
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)

    # Суммируем маски токенов и обрезаем значения, чтобы избежать деления на ноль
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)

    # Вычисляем усредненный эмбеддинг
    return sum_embeddings / sum_mask


def txt2embeddings(
    text: Union[str, List[str]], tokenizer, model, device: str = "cpu"
) -> torch.Tensor:
    """
    Преобразует текст в его векторное представление с использованием модели transformer.

    Parameters:
    - text (str): Текст для преобразования в векторное представление.
    - tokenizer: Токенизатор для предобработки текста.
    - model: Модель transformer для преобразования токенов в вектора.
    - device (str): Устройство для вычислений (cpu или cuda).

    Returns:
    - torch.Tensor: Векторное представление текста.

    Examples:
    >>> text = "Пример текста"
    >>> tokenizer = AutoTokenizer.from_pretrained("bert-base-multilingual-cased")
    >>> model = AutoModel.from_pretrained("bert-base-multilingual-cased")
    >>> embeddings = txt2embeddings(text, tokenizer, model, device="cuda")
    """
    # Кодируем входной текст с помощью токенизатора
    if isinstance(text, str):
        text = [text]
    encoded_input = tokenizer(
        text,
        padding=True,
        truncation=True,
        return_tensors="pt",
        max_length=512,
    )
    # Перемещаем закодированный ввод на указанное устройство
    encoded_input = {k: v.to(device) for k, v in encoded_input.items()}

    # Получаем выход модели для закодированного ввода
    with torch.no_grad():
        model_output = model(**encoded_input)

    # Преобразуем выход модели в векторное представление текста
    return mean_pooling(model_output, encoded_input["attention_mask"])


def load_chatbot(model: str):
    """
    Загружает чатбота для указанной модели.

    Parameters:
    - model (str): Название модели для загрузки чатбота.

    Returns:
    - Conversation: Объект чатбота, готовый для использования.

    Examples:
    >>> chatbot = load_chatbot("TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    """
    # Загружаем чатбот с помощью pipeline из библиотеки transformers
    chatbot = pipeline(
        model=model,
        trust_remote_code=True,
        torch_dtype="auto",
        device_map="cuda",
        task="conversational",
    )
    return chatbot


def generate_answer(chatbot, chat: List[Dict[str, str]], document: str) -> str:
    """
    Генерирует ответ от чатбота на основе предоставленного чата и, возможно, документа.

    Parameters:
    - chatbot (Conversation): Объект чатбота.
    - chat (List[Dict[str, str]]): Список сообщений в чате.
    - document (str): Документ, если он предоставлен.

    Returns:
    - str: Сгенерированный ответ от чатбота.

    Examples:
    >>> chat = [
    >>>     {"role": "user", "content": "Привет, как дела?"},
    >>>     {"role": "system", "content": "Всё отлично, спасибо!"},
    >>> ]
    >>> document = "Это документ для обработки"
    >>> answer = generate_answer(chatbot, chat, document)
    """
    # Создаем объект разговора
    conversation = Conversation()

    # Добавляем системное приветствие
    conversation.add_message({"role": "system", "content": SYSTEM_PROMPT})

    # Добавляем документ, если он предоставлен
    if document:
        document_template = """
        CONTEXT:
        {document}

        Отвечай только на русском языке.
        ВОПРОС:
        """
        conversation.add_message({"role": "user", "content": document_template})

    # Добавляем сообщения из чата
    for message in chat:
        conversation.add_message(
            {"role": message["role"], "content": message["content"]}
        )

    # Генерируем ответ от чатбота
    conversation = chatbot(
        conversation,
        max_new_tokens=512,
        temperature=0.9,
        top_k=50,
        top_p=0.95,
        repetition_penalty=2.0,
        do_sample=True,
        num_beams=5,
        early_stopping=True,
    )

    # Возвращаем последнее сообщение чатбота как ответ
    return conversation[-1]


def load_models(model: str, device: str = "cpu", torch_dtype: str = "auto") -> tuple:
    """
    Загружает токенизатор и модель для указанной предобученной модели.

    Parameters:
    - model (str): Название предобученной модели, поддерживаемой библиотекой transformers.

    Returns:
    - tuple: Кортеж из токенизатора и модели.

    Examples:
    >>> tokenizer, model = load_models("ai-forever/sbert_large_nlu_ru")
    """
    # Загружаем токенизатор для модели
    tokenizer = AutoTokenizer.from_pretrained(
        model, device_map=device, torch_dtype=torch_dtype
    )

    # Загружаем модель
    model = AutoModel.from_pretrained(model, device_map=device, torch_dtype=torch_dtype)

    return tokenizer, model
