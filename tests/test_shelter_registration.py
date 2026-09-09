import json

import app as app_module


def test_register_shelter_is_persisted_and_visible_in_all_shelters():
    data_path = app_module.DATA_FILE
    with open(data_path, encoding='utf-8') as f:
        original_data = json.load(f)

    try:
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        app_module.shelters = []

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'

        response = client.post('/shelter_register', data={'name': '新しい避難所'}, follow_redirects=True)

        assert response.status_code == 200
        assert '新しい避難所' in response.get_data(as_text=True)

        all_response = client.get('/all_shelters')
        assert all_response.status_code == 200
        assert '新しい避難所' in all_response.get_data(as_text=True)

        with open(data_path, encoding='utf-8') as f:
            saved_data = json.load(f)
        assert any(item.get('name') == '新しい避難所' for item in saved_data)
    finally:
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, ensure_ascii=False)
        app_module.shelters = original_data
