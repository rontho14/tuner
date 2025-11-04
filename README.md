**Autores:** 
Guilherme Thomasi Ronca - 22.00522-6
André Prino - 21.00476-5
João Vitor Ferrenha - 22.00085-2 
Matheus Santos Feitosa - 20.00628-4
**Curso/Disciplina:** 
EEN251. Microcontroladores e Sistemas Embarcados.
**Data:** 28/10/2025  

---

## 1. Visão Geral

Este documento descreve o projeto de um **Decibelímetro & Afinador** executado em um **Raspberry Pi**, utilizando como microfone a **webcam PS3 Eye**, com interface **touch** em uma tela de 7". O sistema também envia telemetria para a **Ubidots** (quando conectado), possibilitando visualização de métricas na nuvem. A estrutura e a organização deste relatório seguem como   

Motivação principal: criar uma ferramenta didática e de baixo custo para **medição de nível de pressão sonora** (indicativo) e **afinação** de instrumentos musicais, com interface simples para uso em bancada e coleta/monitoramento no campo.

## Estrutura do Projeto

```
├── main.py          # Ponto de entrada - execute este arquivo
├── app.py           # Classe principal da aplicação
├── config.py        # Constantes de configuração e perfis
├── audio.py         # Gerenciamento de estado e streaming de áudio
├── dsp.py           # Utilitários de processamento digital de sinais
├── ui.py            # Componentes de renderização da UI (Pygame)
└── ubidots.py       # Integração IoT com Ubidots
```

## Visão Geral dos Módulos

### `config.py`
- Constantes e configuração da aplicação
- Perfis de desempenho (ECO para Raspberry Pi, FULL para desktop)
- Definições da paleta de cores
- Frequências de referência das cordas de guitarra

### `dsp.py`
- **`rms_dbfs()`** - Calcula RMS em dBFS
- **`estimate_pitch_autocorr()`** - Detecção de pitch usando autocorrelação
- **`nearest_guitar_string()`** - Encontra a corda de guitarra mais próxima para uma frequência

### `audio.py`
- **`AudioState`** - Dataclass para estado compartilhado de áudio
- **`AudioStream`** - Gerenciador de stream de áudio com buffer

### `ui.py`
- **`UIRenderer`** - Toda a lógica de renderização da UI
  - Visualização do medidor de decibéis
  - Visualização do afinador com mostrador analógico
  - Sobreposição do relatório de gravação
  - Botões e cartões interativos

### `app.py`
- **`App`** - Classe principal da aplicação
  - Thread worker de processamento de áudio
  - Funcionalidade de gravação
  - Tratamento de eventos
  - Loop principal

### `ubidots.py`
- **`post_to_ubidots()`** - Envia dados para a plataforma Ubidots
- **`ubidots_worker()`** - Thread em segundo plano para atualizações IoT periódicas

## Requisitos

```bash
pip install numpy pygame sounddevice requests
```

## Uso

### Executando a Aplicação

```bash
python main.py
```

### Configurando o Token do Ubidots (Opcional)

```bash
export UBIDOTS_TOKEN="seu-token-aqui"
python main.py
```

## Funcionalidades

### Medidor de Decibéis
- Medição de nível sonoro em tempo real
- Indicador de pico mantido
- Gravação manual com estatísticas
- Geração de relatório gráfico

### Afinador de Guitarra
- Detecção de pitch (65 Hz - 1000 Hz)
- Referência de afinação padrão de guitarra (E2, A2, D3, G3, B3, E4)
- Mostrador analógico com faixa de ±100 cents
- Zona visual de "afinado" (±5 cents)

## Suporte de Plataforma

- **Desktop** - Perfil de qualidade total (24 kHz, buffers maiores)
- **Raspberry Pi** - Perfil econômico (12 kHz, desempenho otimizado)

## Benefícios da Estrutura Modular

1. **Melhor Legibilidade** - Cada módulo tem uma única responsabilidade clara
2. **Teste Mais Fácil** - Componentes individuais podem ser testados isoladamente
3. **Melhor Manutenibilidade** - Mudanças são localizadas em módulos específicos
4. **Reusabilidade** - Módulos de DSP e áudio podem ser usados em outros projetos
5. **Dependências Mais Claras** - Declarações de import mostram relacionamentos entre módulos


