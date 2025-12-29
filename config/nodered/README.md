# Node-RED

Low-code programming for event-driven applications.

## Components

- **Deployment**: Node-RED container with persistent storage
- **PVC**: 1GB SSD storage for flows, credentials, and installed nodes
- **Ingress**: Exposed at `nodered.newjoy.ro`

## Data Migration

To migrate data from your existing Docker setup:

1. Deploy Node-RED first (it will create an empty PVC)
2. Find the pod name:
   ```bash
   kubectl get pods -n nodered
   ```
3. Copy your existing data into the pod:
   ```bash
   kubectl cp ./nodered-config/. nodered/<pod-name>:/data/ -c nodered
   ```
4. Restart the pod to pick up the new configuration:
   ```bash
   kubectl rollout restart deployment/nodered -n nodered
   ```

### Important Files

The `/data` directory contains:
- `flows.json` - Your Node-RED flows
- `flows_cred.json` - Encrypted credentials for your flows
- `settings.js` - Node-RED settings (optional customizations)
- `package.json` - Installed npm packages/nodes
- `node_modules/` - Installed node modules

## Configuration

Node-RED is configured with:
- **Timezone**: Europe/Bucharest
- **Port**: 1880 (internal)
- **User/Group**: 1000 (default Node-RED user)

## Security Considerations

Node-RED does not have authentication enabled by default. Consider:

1. **Setting up authentication** in Node-RED's `settings.js`:
   ```javascript
   adminAuth: {
       type: "credentials",
       users: [{
           username: "admin",
           password: "$2b$08$...", // bcrypt hash
           permissions: "*"
       }]
   }
   ```

2. **Using OAuth2 Proxy** for OIDC authentication (like other apps in this cluster):
   - Copy the pattern from `oauth2-proxy-omada` or similar
   - Add an oauth2-proxy deployment in front of Node-RED

## Resources

- **CPU**: 100m request, 1000m limit
- **Memory**: 256Mi request, 1Gi limit
- **Storage**: 1Gi on SSD

