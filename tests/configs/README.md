# 测试配置

配置文件与对应的 skill 同名，用于配合
[mlflow-skills](https://github.com/panlm/mlflow-skills) 测试框架运行。

## aws-best-practice-research

### 启动 MLflow Server

```bash
mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///mlflow.db &
```

### Checklist 场景（默认）

```bash
source .env
python ~/Documents/git/mlflow-skills/tests/test_skill.py \
  tests/configs/aws-best-practice-research.yaml \
  tracking_uri=http://127.0.0.1:5000
```

### Assessment 场景

```bash
source .env
python ~/Documents/git/mlflow-skills/tests/test_skill.py \
  tests/configs/aws-best-practice-research.yaml \
  test_scope=assessment \
  prompt="帮我研究下aws redis最佳实践。同时评估我现有的环境用profile panlm访问美西2region" \
  tracking_uri=http://127.0.0.1:5000
```

所有 yaml 中的字段都可以通过 `KEY=VALUE` 形式在命令行覆盖。
Judge 定义及 scope 说明见 yaml 文件内的注释。
