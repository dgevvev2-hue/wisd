import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const ProxyManagerApp());
}

class ProxyManagerApp extends StatelessWidget {
  const ProxyManagerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Proxy Manager',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  List<ProxyServer> proxyServers = [];
  Map<String, bool> selectedApps = {
    'youtube': true,
    'tiktok': false,
    'instagram': false,
    'telegram': false,
  };
  String? activeProxyId;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    final prefs = await SharedPreferences.getInstance();
    
    final proxyList = prefs.getStringList('proxy_servers') ?? [];
    setState(() {
      proxyServers = proxyList.map((json) => ProxyServer.fromJson(json)).toList();
      if (proxyServers.isEmpty) {
        proxyServers.add(ProxyServer(
          id: 'default',
          name: 'Роутер',
          address: '192.168.0.1:1081',
        ));
      }
      activeProxyId = prefs.getString('active_proxy_id') ?? proxyServers.first.id;
    });

    final apps = prefs.getString('selected_apps');
    if (apps != null) {
      setState(() {
        selectedApps = Map<String, bool>.from(
          (apps.split(',').map((e) => MapEntry(e, true)))
        );
      });
    }
  }

  Future<void> _saveData() async {
    final prefs = await SharedPreferences.getInstance();
    
    final proxyList = proxyServers.map((p) => p.toJson()).toList();
    await prefs.setStringList('proxy_servers', proxyList);
    
    if (activeProxyId != null) {
      await prefs.setString('active_proxy_id', activeProxyId!);
    }

    final apps = selectedApps.entries.where((e) => e.value).map((e) => e.key).join(',');
    await prefs.setString('selected_apps', apps);
  }

  void _addProxy(String name, String address) {
    setState(() {
      proxyServers.add(ProxyServer(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        name: name,
        address: address,
      ));
    });
    _saveData();
  }

  void _deleteProxy(String id) {
    setState(() {
      proxyServers.removeWhere((p) => p.id == id);
      if (activeProxyId == id && proxyServers.isNotEmpty) {
        activeProxyId = proxyServers.first.id;
      }
    });
    _saveData();
  }

  void _setActiveProxy(String id) {
    setState(() {
      activeProxyId = id;
    });
    _saveData();
  }

  void _toggleApp(String app) {
    setState(() {
      selectedApps[app] = !selectedApps[app]!;
    });
    _saveData();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Proxy Manager'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildStatusCard(),
          const SizedBox(height: 24),
          _buildAppsSection(),
          const SizedBox(height: 24),
          _buildProxyServersSection(),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showAddProxyDialog(context),
        child: const Icon(Icons.add),
      ),
    );
  }

  Widget _buildStatusCard() {
    final activeProxy = proxyServers.firstWhere(
      (p) => p.id == activeProxyId,
      orElse: () => proxyServers.first,
    );
    final activeAppsCount = selectedApps.values.where((v) => v).length;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Статус', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            _buildStatusRow('Прокси:', activeProxy.address),
            _buildStatusRow('Активные приложения:', '$activeAppsCount'),
            _buildStatusRow('Статус:', 'Онлайн', isOnline: true),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusRow(String label, String value, {bool isOnline = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          Text(
            value,
            style: TextStyle(
              fontWeight: FontWeight.bold,
              color: isOnline ? Colors.green : null,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAppsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Приложения', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        ...selectedApps.entries.map((entry) {
          final app = entry.key;
          final isSelected = entry.value;
          return _buildAppTile(app, isSelected);
        }).toList(),
      ],
    );
  }

  Widget _buildAppTile(String app, bool isSelected) {
    final appInfo = _getAppInfo(app);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: appInfo['color'],
          child: Text(appInfo['icon'], style: const TextStyle(color: Colors.white)),
        ),
        title: Text(appInfo['name']),
        trailing: Switch(
          value: isSelected,
          onChanged: (_) => _toggleApp(app),
        ),
      ),
    );
  }

  Map<String, dynamic> _getAppInfo(String app) {
    const info = {
      'youtube': {'name': 'YouTube', 'icon': '▶', 'color': Colors.red},
      'tiktok': {'name': 'TikTok', 'icon': '♪', 'color': Colors.black},
      'instagram': {'name': 'Instagram', 'icon': '📷', 'color': Colors.purple},
      'telegram': {'name': 'Telegram', 'icon': '✈', 'color': Colors.blue},
    };
    return info[app] ?? {'name': app, 'icon': '?', 'color': Colors.grey};
  }

  Widget _buildProxyServersSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Прокси серверы', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        ...proxyServers.map((proxy) => _buildProxyTile(proxy)).toList(),
      ],
    );
  }

  Widget _buildProxyTile(ProxyServer proxy) {
    final isActive = proxy.id == activeProxyId;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: isActive ? Colors.blue.withOpacity(0.1) : null,
      child: ListTile(
        title: Text(proxy.name),
        subtitle: Text(proxy.address),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (isActive)
              const Icon(Icons.check_circle, color: Colors.green)
            else
              IconButton(
                icon: const Icon(Icons.play_circle_outline),
                onPressed: () => _setActiveProxy(proxy.id),
              ),
            IconButton(
              icon: const Icon(Icons.delete, color: Colors.red),
              onPressed: proxy.id == 'default' ? null : () => _deleteProxy(proxy.id),
            ),
          ],
        ),
      ),
    );
  }

  void _showAddProxyDialog(BuildContext context) {
    final nameController = TextEditingController();
    final addressController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Добавить прокси'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: const InputDecoration(labelText: 'Название'),
            ),
            TextField(
              controller: addressController,
              decoration: const InputDecoration(labelText: 'Адрес (IP:Порт)'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () {
              if (nameController.text.isNotEmpty && addressController.text.isNotEmpty) {
                _addProxy(nameController.text, addressController.text);
                Navigator.pop(context);
              }
            },
            child: const Text('Добавить'),
          ),
        ],
      ),
    );
  }
}

class ProxyServer {
  final String id;
  final String name;
  final String address;

  ProxyServer({
    required this.id,
    required this.name,
    required this.address,
  });

  factory ProxyServer.fromJson(String json) {
    final parts = json.split('|');
    return ProxyServer(
      id: parts[0],
      name: parts[1],
      address: parts[2],
    );
  }

  String toJson() {
    return '$id|$name|$address';
  }
}
