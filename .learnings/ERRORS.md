# 错误日志

记录系统运行中遇到的错误和异常。

---

## 格式说明

每条错误记录使用以下格式：

```
## [ERR-YYYYMMDD-XXX] component_name

**Logged**: ISO-8601 timestamp
**Priority**: high | critical
**Status**: pending | resolved
**Area**: api | data_source | analysis | frontend

### Summary
简短描述错误

### Error
```
实际错误信息或堆栈跟踪
```

### Context
- 触发条件
- 输入参数
- 环境信息

### Suggested Fix
可能的解决方案

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.py
```

---

## 错误记录

（暂无记录）
